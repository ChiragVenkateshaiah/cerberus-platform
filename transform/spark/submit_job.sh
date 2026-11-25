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
NAMESPACE="spark-jobs"

# 17.5: the downloads silver job reuses this script through these overrides
# (orchestration/launch_exercise.sh sets them). The defaults are the payments
# job, so a bare ./submit_job.sh renders and runs exactly as before.
#   APP_NAME       the SparkApplication's name
#   SCRIPT_NAME    the Python file in this directory to upload
#   MANIFEST_YAML  the SparkApplication YAML in this directory
#   EXTRA_SED      a sed script applied to the rendered manifest after the
#                  lineage substitution (placeholder values; empty by default)
APP_NAME="${APP_NAME:-cerberus-promote-payments}"
SCRIPT_NAME="${SCRIPT_NAME:-promote_payments_spark.py}"
MANIFEST_YAML="${MANIFEST_YAML:-spark-application.yaml}"
EXTRA_SED="${EXTRA_SED:-}"
SCRIPT_S3_KEY="_spark_jobs/$SCRIPT_NAME"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "uploading $SCRIPT_NAME to s3://$SILVER_BUCKET/$SCRIPT_S3_KEY"
aws s3 cp "$SCRIPT_DIR/$SCRIPT_NAME" \
  "s3://$SILVER_BUCKET/$SCRIPT_S3_KEY" \
  --profile "$TRANSFORM_PROFILE" --region "$AWS_REGION"

log "pointing kubectl at $CLUSTER_NAME"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" --profile "$ADMIN_PROFILE" >/dev/null

# Clears any previous run of the same SparkApplication -- the operator
# doesn't resubmit over an existing one, and this job is meant to be rerun
# each time the stack is spun up, not accumulate history.
kubectl delete sparkapplication "$APP_NAME" -n "$NAMESPACE" --ignore-not-found

# 6.4c: resolve spark-application.yaml's __OPENLINEAGE_URL__ placeholder,
# same as the orchestrated entrypoint_transform.sh. Take OPENLINEAGE_URL
# from the environment, else try the dev-standing output, else fall back to
# a console transport so a bare `./submit_job.sh` still works.
OPENLINEAGE_URL="${OPENLINEAGE_URL:-$(cd "$SCRIPT_DIR/../../terraform/envs/dev-standing" \
  && terraform output -raw lineage_collector_url 2>/dev/null || true)}"
MANIFEST="$(mktemp)"
if [[ -n "$OPENLINEAGE_URL" ]]; then
  log "lineage: OpenLineage events -> $OPENLINEAGE_URL"
  sed "s|__OPENLINEAGE_URL__|${OPENLINEAGE_URL}|" "$SCRIPT_DIR/$MANIFEST_YAML" >"$MANIFEST"
else
  log "lineage: no OPENLINEAGE_URL -- Spark events to the driver console only"
  sed -e 's|spark.openlineage.transport.type: "http"|spark.openlineage.transport.type: "console"|' \
    -e '/spark.openlineage.transport.url:/d' \
    "$SCRIPT_DIR/$MANIFEST_YAML" >"$MANIFEST"
fi

if [[ -n "$EXTRA_SED" ]]; then
  sed -i -e "$EXTRA_SED" "$MANIFEST"
fi

log "submitting $APP_NAME"
kubectl apply -f "$MANIFEST"

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

log "job completed -- silver committed through the Iceberg Glue catalog (8.5: no MSCK REPAIR)"
