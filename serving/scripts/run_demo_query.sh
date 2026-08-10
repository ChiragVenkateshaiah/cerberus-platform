#!/usr/bin/env bash
set -euo pipefail

# Cerberus 1.10 -- runs serving/queries/demo_query.sql through Athena as the
# cerberus-serving IAM role (assumed via the cerberus-serving AWS CLI
# profile, role_arn + source_profile chaining -- same pattern as 1.9's
# cerberus-transform profile), proving the read-only serving path works
# end to end rather than just that the policy was declared.

AWS_PROFILE="cerberus-serving"
AWS_REGION="us-east-1"
WORKGROUP="cerberus_platform"
DATABASE="cerberus_platform"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUERY_FILE="$SCRIPT_DIR/../queries/demo_query.sql"

QUERY="$(cat "$QUERY_FILE")"

echo "[$(date -u +%FT%TZ)] submitting demo query as cerberus-serving"

QUERY_EXECUTION_ID="$(aws athena start-query-execution \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --work-group "$WORKGROUP" \
  --query-execution-context "Database=$DATABASE" \
  --query-string "$QUERY" \
  --output text --query 'QueryExecutionId')"

echo "[$(date -u +%FT%TZ)] query execution id: $QUERY_EXECUTION_ID"

STATE="RUNNING"
while [[ "$STATE" == "RUNNING" || "$STATE" == "QUEUED" ]]; do
  sleep 1
  STATE="$(aws athena get-query-execution \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --query-execution-id "$QUERY_EXECUTION_ID" \
    --output text --query 'QueryExecution.Status.State')"
done

if [[ "$STATE" != "SUCCEEDED" ]]; then
  echo "[$(date -u +%FT%TZ)] query $STATE" >&2
  aws athena get-query-execution \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --query-execution-id "$QUERY_EXECUTION_ID" \
    --query 'QueryExecution.Status.StateChangeReason' --output text >&2
  exit 1
fi

echo "[$(date -u +%FT%TZ)] query succeeded, results:"
echo ""

aws athena get-query-results \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --query-execution-id "$QUERY_EXECUTION_ID" \
  --output json \
| jq -r '.ResultSet.Rows[] | [.Data[].VarCharValue] | @tsv' \
| column -t -s $'\t'
