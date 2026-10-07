#!/usr/bin/env bash
set -euo pipefail

# Cerberus 8.3 -- runs generate_bulk_payments.py on the dev-compute cluster
# (ADR 0018). Writes JSON Lines into
# s3://<bronze>/payments_bulk/run_id=<RUN_ID>/dt=YYYY-MM-DD/.
#
#   ./generate_bulk.sh EVENTS [RUN_ID] [NOW]
#
#   EVENTS  target event count, e.g. 1000000
#   RUN_ID  defaults to e<EVENTS>-<UTC timestamp>
#   NOW     the run's fixed "now", YYYY-MM-DDTHH:MM:SSZ; defaults to the
#           current UTC second
#
# To re-run a run (after a failure, say), pass the same EVENTS, RUN_ID and
# NOW printed at the start: the output is identical and replaces only that
# run's directories. A different NOW or EVENTS under the same RUN_ID would
# replace the old run with different data.
#
# EXECUTORS (env, default 2) sets the executor count.
#
# Same credential split as submit_job.sh: cerberus-transform uploads the
# script, cerberus-admin drives kubectl, and the job itself runs as
# cerberus-spark via IRSA. Prerequisite: envs/dev-compute applied, which also
# applies iam_spark's payments_bulk/ grant.

if [[ $# -lt 1 ]]; then
  echo "usage: $0 EVENTS [RUN_ID] [NOW]" >&2
  exit 2
fi

EVENTS="$1"
NOW="${3:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
RUN_ID="${2:-e${EVENTS}-$(date -u -d "$NOW" +%Y%m%dT%H%M%SZ)}"
EXECUTORS="${EXECUTORS:-2}"

CLUSTER_NAME="cerberus-platform-eks"
AWS_REGION="us-east-1"
TRANSFORM_PROFILE="cerberus-transform"
ADMIN_PROFILE="cerberus-admin"
SILVER_BUCKET="cerberus-platform-silver-131715059025"
SCRIPT_S3_KEY="_spark_jobs/generate_bulk_payments.py"
NAMESPACE="spark-jobs"
APP_NAME="cerberus-generate-bulk-payments"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "run: EVENTS=$EVENTS RUN_ID=$RUN_ID NOW=$NOW EXECUTORS=$EXECUTORS"
log "re-run with: EXECUTORS=$EXECUTORS $0 $EVENTS $RUN_ID $NOW"

log "uploading generate_bulk_payments.py to s3://$SILVER_BUCKET/$SCRIPT_S3_KEY"
aws s3 cp "$SCRIPT_DIR/generate_bulk_payments.py" \
  "s3://$SILVER_BUCKET/$SCRIPT_S3_KEY" \
  --profile "$TRANSFORM_PROFILE" --region "$AWS_REGION"

log "pointing kubectl at $CLUSTER_NAME"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" --profile "$ADMIN_PROFILE" >/dev/null

# The operator doesn't resubmit over an existing SparkApplication.
kubectl delete sparkapplication "$APP_NAME" -n "$NAMESPACE" --ignore-not-found

MANIFEST="$(mktemp)"
sed -e "s|__RUN_ID__|${RUN_ID}|" \
  -e "s|__EVENTS__|${EVENTS}|" \
  -e "s|__NOW__|${NOW}|" \
  -e "s|__EXECUTORS__|${EXECUTORS}|" \
  "$SCRIPT_DIR/spark-application-generate.yaml" >"$MANIFEST"

STARTED="$(date -u +%s)"
log "submitting $APP_NAME"
kubectl apply -f "$MANIFEST"

STATE=""
while [[ "$STATE" != "COMPLETED" && "$STATE" != "FAILED" ]]; do
  sleep 10
  STATE="$(kubectl get sparkapplication "$APP_NAME" -n "$NAMESPACE" \
    -o jsonpath='{.status.applicationState.state}' 2>/dev/null || true)"
  log "state: ${STATE:-<not yet reported>}"
done

log "wall time: $(($(date -u +%s) - STARTED))s"

if [[ "$STATE" != "COMPLETED" ]]; then
  log "job $STATE -- driver logs:"
  kubectl logs "${APP_NAME}-driver" -n "$NAMESPACE" || true
  exit 1
fi

# The driver's [generate] lines are this run's manifest: events per dt=,
# total, and write throughput. Keep them for the 8.4 reconciliation.
log "job completed -- run summary:"
kubectl logs "${APP_NAME}-driver" -n "$NAMESPACE" | grep '^\[generate\]'
