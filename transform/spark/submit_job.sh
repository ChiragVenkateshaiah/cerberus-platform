#!/usr/bin/env bash
set -euo pipefail

# Cerberus 3.5/3.6 -- runs promote_payments_spark.py on the EKS cluster
# built in 3.2, through the Spark Operator installed in 3.4. Not
# Terraform-managed (see terraform/modules/spark_job/main.tf's header) --
# submitting and verifying a job run is a workload action, taken by hand
# each time this spin-up/destroy stack is actually exercised, not
# infrastructure Terraform should reconcile on every apply.
#
# Three separate credentials, least-privilege throughout: cerberus-transform
# uploads the script and runs the post-job Glue repair (it already has
# read/write on silver and Glue/Athena permissions from 1.6/1.8); cerberus-admin
# is the only identity with cluster-admin kubectl access (granted via the eks
# module's bootstrap_cluster_creator_admin_permissions, since it's the
# identity that ran terraform apply); the job itself runs as cerberus-spark,
# assumed via IRSA, never as either of the above.
#
# Prerequisites this script does NOT do for you: `terraform apply` against
# envs/dev-standing (once) and envs/dev-compute (this stack must actually
# exist first -- ADR 0011 split the old single envs/dev root in two), and
# confirming spark-application.yaml's image/hadoop-aws versions are current
# (see that file's header).

CLUSTER_NAME="cerberus-platform-eks"
AWS_REGION="us-east-1"
TRANSFORM_PROFILE="cerberus-transform"
ADMIN_PROFILE="cerberus-admin"
SILVER_BUCKET="cerberus-platform-silver-131715059025"
SCRIPT_S3_KEY="_spark_jobs/promote_payments_spark.py"
NAMESPACE="spark-jobs"
APP_NAME="cerberus-promote-payments"
GLUE_DATABASE="cerberus_platform"
GLUE_SILVER_TABLE="payments_events"
ATHENA_WORKGROUP="cerberus_platform"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "uploading promote_payments_spark.py to s3://$SILVER_BUCKET/$SCRIPT_S3_KEY"
aws s3 cp "$SCRIPT_DIR/promote_payments_spark.py" \
  "s3://$SILVER_BUCKET/$SCRIPT_S3_KEY" \
  --profile "$TRANSFORM_PROFILE" --region "$AWS_REGION"

log "pointing kubectl at $CLUSTER_NAME"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" --profile "$ADMIN_PROFILE" >/dev/null

# Clears any previous run of the same SparkApplication -- the operator
# doesn't resubmit over an existing one, and this job is meant to be rerun
# each time the stack is spun up, not accumulate history.
kubectl delete sparkapplication "$APP_NAME" -n "$NAMESPACE" --ignore-not-found

log "submitting $APP_NAME"
kubectl apply -f "$SCRIPT_DIR/spark-application.yaml"

log "waiting for $APP_NAME to complete"
STATE=""
while [[ "$STATE" != "COMPLETED" && "$STATE" != "FAILED" ]]; do
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
  --profile "$TRANSFORM_PROFILE" \
  --region "$AWS_REGION" \
  --work-group "$ATHENA_WORKGROUP" \
  --query-execution-context "Database=$GLUE_DATABASE" \
  --query-string "MSCK REPAIR TABLE $GLUE_SILVER_TABLE" \
  --output text --query 'QueryExecutionId')"

REPAIR_STATE="RUNNING"
while [[ "$REPAIR_STATE" == "RUNNING" || "$REPAIR_STATE" == "QUEUED" ]]; do
  sleep 1
  REPAIR_STATE="$(aws athena get-query-execution \
    --profile "$TRANSFORM_PROFILE" \
    --region "$AWS_REGION" \
    --query-execution-id "$QUERY_EXECUTION_ID" \
    --output text --query 'QueryExecution.Status.State')"
done

if [[ "$REPAIR_STATE" != "SUCCEEDED" ]]; then
  log "MSCK REPAIR TABLE $REPAIR_STATE" >&2
  aws athena get-query-execution \
    --profile "$TRANSFORM_PROFILE" \
    --region "$AWS_REGION" \
    --query-execution-id "$QUERY_EXECUTION_ID" \
    --query 'QueryExecution.Status.StateChangeReason' --output text >&2
  exit 1
fi

log "done -- silver's new partitions are registered and queryable"
