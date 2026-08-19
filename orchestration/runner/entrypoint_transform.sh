#!/usr/bin/env bash
set -euo pipefail

# Containerized adaptation of transform/spark/submit_job.sh (3.5/3.6) --
# runs inside the "transform" ECS Fargate task Step Functions invokes via
# RunTransform (orchestration/state_machine.asl.json.tftpl, 4.2). Same
# kubectl-apply/poll + MSCK REPAIR/poll structure as the original, adapted
# for two things that differ inside a task instead of on a laptop: no
# named CLI profile (the task role, cerberus-orchestration-transform,
# supplies credentials directly via the container credentials endpoint),
# and no local file paths (the files this needs are baked into the image
# at /opt/spark, not read from a relative SCRIPT_DIR).
#
# NB on SILVER_BUCKET/SCRIPT_S3_KEY below vs. spark-application.yaml:
# that manifest's mainApplicationFile is a hardcoded s3a:// path baked
# into the image (Dockerfile), not templated from these env vars -- same
# as the original submit_job.sh, where SILVER_BUCKET was a fixed bash
# constant a human had to keep matching the YAML by hand. In practice
# they don't drift: both resolve to the same s3_medallion-managed silver
# bucket name. If SILVER_BUCKET is ever pointed at something other than
# that bucket, the upload below and the SparkApplication's own read will
# disagree, and the job will fail with a driver-pod FileNotFoundError
# that gives no hint the real mismatch is here.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

CLUSTER_NAME="${CLUSTER_NAME:?}"
AWS_REGION="${AWS_REGION:?}"
SILVER_BUCKET="${SILVER_BUCKET:?}"
SCRIPT_S3_KEY="${SCRIPT_S3_KEY:-_spark_jobs/promote_payments_spark.py}"
NAMESPACE="${NAMESPACE:-spark-jobs}"
APP_NAME="${APP_NAME:-cerberus-promote-payments}"
GLUE_DATABASE="${GLUE_DATABASE:?}"
GLUE_SILVER_TABLE="${GLUE_SILVER_TABLE:-payments_events}"
ATHENA_WORKGROUP="${ATHENA_WORKGROUP:?}"

# Bounds on both poll loops below -- an earlier version of this script had
# none, and the Spark-state loop's `|| true` (needed so one transient
# kubectl API blip doesn't kill the whole task) meant a persistent failure
# (RBAC/access-entry propagation delay, EKS API outage) left STATE empty
# forever with no way for the loop to ever exit. Unlike the original
# submit_job.sh, run interactively where a human could Ctrl-C, this runs
# unattended inside a Step Functions execution -- an unbounded hang here
# burns real Fargate cost with no automatic failure. 5s * 240 = 20
# minutes for the Spark job; 1s * 300 = 5 minutes for the MSCK REPAIR.
SPARK_POLL_MAX_ATTEMPTS=240
REPAIR_POLL_MAX_ATTEMPTS=300

log "uploading promote_payments_spark.py to s3://$SILVER_BUCKET/$SCRIPT_S3_KEY"
aws s3 cp /opt/spark/promote_payments_spark.py \
  "s3://$SILVER_BUCKET/$SCRIPT_S3_KEY" \
  --region "$AWS_REGION"

log "pointing kubectl at $CLUSTER_NAME"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null

# Clears any previous run of the same SparkApplication -- see
# submit_job.sh's original comment: the operator doesn't resubmit over an
# existing one, and this job is meant to be rerun each time the pipeline
# runs, not accumulate history.
kubectl delete sparkapplication "$APP_NAME" -n "$NAMESPACE" --ignore-not-found

log "submitting $APP_NAME"
kubectl apply -f /opt/spark/spark-application.yaml

log "waiting for $APP_NAME to complete"
STATE=""
ATTEMPT=0
while [[ "$STATE" != "COMPLETED" && "$STATE" != "FAILED" ]]; do
  if (( ATTEMPT >= SPARK_POLL_MAX_ATTEMPTS )); then
    log "timed out after $ATTEMPT polls waiting for $APP_NAME to complete" >&2
    exit 1
  fi
  ATTEMPT=$((ATTEMPT + 1))
  sleep 5
  STATE="$(kubectl get sparkapplication "$APP_NAME" -n "$NAMESPACE" \
    -o jsonpath='{.status.applicationState.state}' 2>/dev/null || true)"
  log "state: ${STATE:-<not yet reported>}"
done

if [[ "$STATE" != "COMPLETED" ]]; then
  log "job $STATE -- driver logs:"
  kubectl logs "${APP_NAME}-driver" -n "$NAMESPACE" || true
  exit 1
fi

log "job completed -- registering new silver partitions via MSCK REPAIR TABLE"

QUERY_EXECUTION_ID="$(aws athena start-query-execution \
  --region "$AWS_REGION" \
  --work-group "$ATHENA_WORKGROUP" \
  --query-execution-context "Database=$GLUE_DATABASE" \
  --query-string "MSCK REPAIR TABLE $GLUE_SILVER_TABLE" \
  --output text --query 'QueryExecutionId')"

REPAIR_STATE="RUNNING"
ATTEMPT=0
while [[ "$REPAIR_STATE" == "RUNNING" || "$REPAIR_STATE" == "QUEUED" ]]; do
  if (( ATTEMPT >= REPAIR_POLL_MAX_ATTEMPTS )); then
    log "timed out after $ATTEMPT polls waiting for MSCK REPAIR TABLE to finish" >&2
    exit 1
  fi
  ATTEMPT=$((ATTEMPT + 1))
  sleep 1
  REPAIR_STATE="$(aws athena get-query-execution \
    --region "$AWS_REGION" \
    --query-execution-id "$QUERY_EXECUTION_ID" \
    --output text --query 'QueryExecution.Status.State')"
done

if [[ "$REPAIR_STATE" != "SUCCEEDED" ]]; then
  log "MSCK REPAIR TABLE $REPAIR_STATE" >&2
  aws athena get-query-execution \
    --region "$AWS_REGION" \
    --query-execution-id "$QUERY_EXECUTION_ID" \
    --query 'QueryExecution.Status.StateChangeReason' --output text >&2
  exit 1
fi

log "done -- silver's new partitions are registered and queryable"
