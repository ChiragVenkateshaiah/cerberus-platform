#!/usr/bin/env bash
set -uo pipefail

# Cerberus step 10 -- the account check for a live Grafana session (ADR 0024,
# plan docs/plans/2026-11-12-console-session.md section 5). Read-only: it
# creates and changes nothing. Prints `key value` lines and exits 1 when any
# session count is not zero. A value it cannot read prints `error` and also
# fails: a failed read is never taken as a zero.
#
#   orchestration/console_check.sh
#
# The first four counts are the account-wide counts exercise.sh prints after
# its destroy (EKS, NAT, EIP, running instances). They are replicated here,
# not shared: exercise.sh --check only looks at identity and state, and
# exercise.sh must not change. Do not run a session and an exercise at the
# same time; each trips the other's check.
#
# Standing resource IDs (bucket, user pool, console subnet and route table)
# come from `terraform output` of dev-standing, as `make console-artifacts`
# does. Those outputs are the one source that cannot drift from the real
# resources, and no ID is written into the repo. If dev-standing cannot be
# read, the check fails.
#
# Nothing here prints the account ID, the bucket name or a domain, and AWS
# error text is discarded because it can carry ARNs.

REGION="us-east-1"
export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="$REGION"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF="${TF_BIN:-terraform}"
NAME="cerberus-console-grafana"
FAIL=0

aws_() { aws --region "$REGION" "$@"; }
# Print "key value"; any value but 0 fails the check.
report() {
  echo "$1 $2"
  [[ "$2" == "0" ]] || FAIL=1
}
# Informational: printed, never fails the check.
info() { echo "$1 $2"; }
# Run a query; print its value, or "error".
val() {
  local out
  if out="$("$@" 2>/dev/null)"; then echo "$out"; else echo "error"; fi
}
# 1 if the IAM resource exists, 0 if NoSuchEntity, else "error".
present() {
  local out
  if "$@" >/dev/null 2>&1; then
    echo 1
    return
  fi
  out="$("$@" 2>&1)"
  if grep -q 'NoSuchEntity' <<<"$out"; then echo 0; else echo error; fi
}

command -v jq >/dev/null || { echo "error jq-missing"; exit 1; }

# --- standing outputs -------------------------------------------------------
if ! outputs="$("$TF" -chdir="$REPO/terraform/envs/dev-standing" output -json 2>/dev/null)"; then
  echo "error dev-standing-outputs-unreadable"
  exit 1
fi
BUCKET="$(jq -r '.console_site_bucket_name.value // empty' <<<"$outputs")"
POOL="$(jq -r '.console_user_pool_id.value // empty' <<<"$outputs")"
SUBNET="$(jq -r '.console_subnet_id.value // empty' <<<"$outputs")"
ROUTE_TABLE="$(jq -r '.console_route_table_id.value // empty' <<<"$outputs")"
if [[ -z "$BUCKET" || -z "$POOL" || -z "$SUBNET" || -z "$ROUTE_TABLE" ]]; then
  echo "error dev-standing-outputs-incomplete"
  exit 1
fi

# --- the four exercise.sh counts --------------------------------------------
report eks_clusters "$(val aws_ eks list-clusters --query 'length(clusters)' --output text)"
report nat_gateways "$(val aws_ ec2 describe-nat-gateways \
  --filter Name=state,Values=pending,available --query 'length(NatGateways)' --output text)"
report elastic_ips "$(val aws_ ec2 describe-addresses --query 'length(Addresses)' --output text)"
report running_instances "$(val aws_ ec2 describe-instances \
  --filters Name=instance-state-name,Values=pending,running \
  --query 'length(Reservations[].Instances[])' --output text)"

# --- session resources -------------------------------------------------------
report console_instances "$(val aws_ ec2 describe-instances \
  --filters Name=tag:Stack,Values=dev-console \
  Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down \
  --query 'length(Reservations[].Instances[])' --output text)"
# CloudFront is global; its tags are indexed in us-east-1. The Tagging API may
# lag after a destroy; PR F decides whether this becomes informational.
report distributions_tagged "$(val aws_ resourcegroupstaggingapi get-resources \
  --resource-type-filters cloudfront:distribution \
  --tag-filters Key=Stack,Values=dev-console \
  --query 'length(ResourceTagMappingList)' --output text)"
# shellcheck disable=SC2016  # the backticks are JMESPath literals, not shell
# The standing console edge is the one distribution that is allowed. Any other
# count (an untagged leftover, or the edge missing) fails the check.
total="$(val aws_ cloudfront list-distributions \
  --query 'length(DistributionList.Items || `[]`)' --output text)"
echo "distributions_total $total (expected 1: the standing edge)"
[[ "$total" == "1" ]] || FAIL=1
# shellcheck disable=SC2016
report vpc_origins "$(val aws_ cloudfront list-vpc-origins \
  --query 'length(VpcOriginList.Items || `[]`)' --output text)"
report cognito_clients "$(val aws_ cognito-idp list-user-pool-clients \
  --user-pool-id "$POOL" --max-results 60 \
  --query "length(UserPoolClients[?ClientName=='$NAME'])" --output text)"
report iam_role "$(present aws_ iam get-role --role-name "$NAME")"
report iam_instance_profile "$(present aws_ iam get-instance-profile --instance-profile-name "$NAME")"
report security_group "$(val aws_ ec2 describe-security-groups \
  --filters Name=group-name,Values="$NAME" --query 'length(SecurityGroups)' --output text)"
report console_default_routes "$(val aws_ ec2 describe-route-tables --route-table-ids "$ROUTE_TABLE" \
  --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'] | length(@)" --output text)"
# shellcheck disable=SC2016
report live_json "$(val aws_ s3api list-objects-v2 --bucket "$BUCKET" --prefix live.json \
  --max-keys 10 --query "length(Contents[?Key=='live.json'] || \`[]\`)" --output text)"
# shellcheck disable=SC2016
report session_artifacts "$(val aws_ s3api list-objects-v2 --bucket "$BUCKET" \
  --prefix artifacts/session/ --max-keys 1000 --query 'length(Contents || `[]`)' --output text)"

# --- dev-console state ------------------------------------------------------
# Same partial-backend init as `make console-plan`. Fail closed: an error
# reading state must not look like an empty state.
# A first run has no state object: `state list` then exits 1 with "No state
# file was found!", which means an empty state. Any other failure is `error`.
if "$REPO/orchestration/console_init.sh" -no-color >/dev/null 2>&1; then
  if state="$("$TF" -chdir="$REPO/terraform/envs/dev-console" state list -no-color 2>&1)"; then
    report dev_console_state "$(grep -c '^[a-z]' <<<"$state" || true)"
  elif grep -q 'No state file was found' <<<"$state"; then
    report dev_console_state 0
  else
    report dev_console_state error
  fi
else
  report dev_console_state error
fi

# --- informational ----------------------------------------------------------
# Network interfaces in the console subnet (the VPC origin's clear about a
# minute after its delete) and the CloudFront service SG, which lingers a few
# minutes after the origin is gone. Neither bills; neither fails the check.
info console_subnet_enis "$(val aws_ ec2 describe-network-interfaces \
  --filters Name=subnet-id,Values="$SUBNET" --query 'length(NetworkInterfaces)' --output text)"
info cloudfront_service_sgs "$(val aws_ ec2 describe-security-groups \
  --filters Name=tag-key,Values=aws.cloudfront.vpcorigin --query 'length(SecurityGroups)' --output text)"

if ((FAIL)); then
  echo "console_check FAILED: something from a session is still up, or could not be read"
  exit 1
fi
echo "console_check ok"
