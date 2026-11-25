#!/usr/bin/env bash
set -uo pipefail

# Phase 17.4 -- the account check for a launch session (ADR 0030 Decision 2).
# Read-only: it creates and changes nothing. Prints `key value` lines and exits 1
# when any count is not zero. A value it cannot read prints `error` and also
# fails: a failed read is never taken as a zero.
#
#   orchestration/launch_check.sh
#
# Copied in shape from console_check.sh. Public keys and key groups cannot be
# tagged, so they (and the cache policy and OAC) are found by the
# cerberus-launch- name prefix; the rest by the Stack=dev-launch tag or a fixed
# name. The standing console edge is the one distribution that is allowed.
# Nothing here prints the account ID, a bucket name or a domain, and AWS error
# text is discarded because it can carry ARNs.

REGION="us-east-1"
export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="$REGION"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF="${TF_BIN:-terraform}"
NAME="cerberus-launch-loadgen"
PREFIX="cerberus-launch-"
PARAM="/cerberus/launch/session-cookies"
FAIL=0

aws_() { aws --region "$REGION" "$@"; }
# Print "key value"; any value but 0 fails the check.
report() {
  echo "$1 $2"
  [[ "$2" == "0" ]] || FAIL=1
}
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
# 1 if the bucket exists, 0 if it is not found (404), else "error".
bucket_present() {
  local out
  if aws_ s3api head-bucket --bucket "$1" >/dev/null 2>&1; then
    echo 1
    return
  fi
  out="$(aws_ s3api head-bucket --bucket "$1" 2>&1)"
  if grep -Eq '404|Not Found|NoSuchBucket' <<<"$out"; then echo 0; else echo error; fi
}
# Count of `<jmespath>` over a CLI call, with a prefix filter built in the query.
count() { val aws_ "$@" --output text; }

command -v jq >/dev/null || { echo "error jq-missing"; exit 1; }

# --- CloudFront --------------------------------------------------------------
# shellcheck disable=SC2016  # the backticks are JMESPath literals, not shell
total="$(val aws_ cloudfront list-distributions \
  --query 'length(DistributionList.Items || `[]`)' --output text)"
# The standing console edge is the one allowed distribution: report the rest.
if [[ "$total" =~ ^[0-9]+$ ]]; then
  extra=$((total > 1 ? total - 1 : 0))
  # Zero distributions means the standing edge is missing: not a launch leftover.
  report distributions_beyond_standing "$extra"
else
  report distributions_beyond_standing error
fi
report distributions_tagged "$(val aws_ resourcegroupstaggingapi get-resources \
  --resource-type-filters cloudfront:distribution \
  --tag-filters Key=Stack,Values=dev-launch \
  --query 'length(ResourceTagMappingList)' --output text)"
# shellcheck disable=SC2016
report cloudfront_functions "$(count cloudfront list-functions \
  --query "length(FunctionList.Items[?starts_with(Name, '$PREFIX')] || \`[]\`)")"
# shellcheck disable=SC2016
report key_value_stores "$(count cloudfront list-key-value-stores \
  --query "length(KeyValueStoreList.Items[?starts_with(Name, '$PREFIX')] || \`[]\`)")"
# shellcheck disable=SC2016
report public_keys "$(count cloudfront list-public-keys \
  --query "length(PublicKeyList.Items[?starts_with(Name, '$PREFIX')] || \`[]\`)")"
# shellcheck disable=SC2016
report key_groups "$(count cloudfront list-key-groups \
  --query "length(KeyGroupList.Items[?starts_with(KeyGroup.KeyGroupConfig.Name, '$PREFIX')] || \`[]\`)")"
# shellcheck disable=SC2016
report cache_policies "$(count cloudfront list-cache-policies --type custom \
  --query "length(CachePolicyList.Items[?starts_with(CachePolicy.CachePolicyConfig.Name, '$PREFIX')] || \`[]\`)")"
# shellcheck disable=SC2016
report origin_access_controls "$(count cloudfront list-origin-access-controls \
  --query "length(OriginAccessControlList.Items[?starts_with(Name, '$PREFIX')] || \`[]\`)")"

# --- CloudWatch Logs delivery -----------------------------------------------
# shellcheck disable=SC2016
report log_delivery_sources "$(count logs describe-delivery-sources \
  --query "length(deliverySources[?starts_with(name, '$PREFIX')] || \`[]\`)")"
# shellcheck disable=SC2016
report log_delivery_destinations "$(count logs describe-delivery-destinations \
  --query "length(deliveryDestinations[?starts_with(name, '$PREFIX')] || \`[]\`)")"
# shellcheck disable=SC2016
report log_deliveries "$(count logs describe-deliveries \
  --query "length(deliveries[?starts_with(deliverySourceName, '$PREFIX')] || \`[]\`)")"

# --- EC2 and IAM -------------------------------------------------------------
report launch_instances "$(val aws_ ec2 describe-instances \
  --filters Name=tag:Stack,Values=dev-launch \
  Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down \
  --query 'length(Reservations[].Instances[])' --output text)"
report launch_volumes "$(val aws_ ec2 describe-volumes \
  --filters Name=tag:Stack,Values=dev-launch --query 'length(Volumes)' --output text)"
report launch_spot_requests "$(val aws_ ec2 describe-spot-instance-requests \
  --filters Name=tag:Stack,Values=dev-launch Name=state,Values=open,active,disabled \
  --query 'length(SpotInstanceRequests)' --output text)"
report security_group "$(val aws_ ec2 describe-security-groups \
  --filters Name=group-name,Values="$NAME" --query 'length(SecurityGroups)' --output text)"
report iam_role "$(present aws_ iam get-role --role-name "$NAME")"
report iam_instance_profile "$(present aws_ iam get-instance-profile --instance-profile-name "$NAME")"

# --- the cookie parameter (describe only: never decrypted) -------------------
report cookie_parameter "$(val aws_ ssm describe-parameters \
  --parameter-filters "Key=Name,Option=Equals,Values=$PARAM" \
  --query 'length(Parameters)' --output text)"

# --- buckets, by the computed name -------------------------------------------
acct="$(aws_ sts get-caller-identity --query Account --output text 2>/dev/null)" || acct=""
if [[ -n "$acct" ]]; then
  report build_bucket "$(bucket_present "cerberus-platform-launch-build-$acct")"
  report log_bucket "$(bucket_present "cerberus-platform-launch-logs-$acct")"
else
  report build_bucket error
  report log_bucket error
fi

# --- dev-launch state --------------------------------------------------------
# Fail closed: an error reading state must not look like an empty state. A first
# run has no state object ("No state file was found!"): that is an empty state.
if "$REPO/orchestration/launch_init.sh" -no-color >/dev/null 2>&1; then
  if state="$("$TF" -chdir="$REPO/terraform/envs/dev-launch" state list -no-color 2>&1)"; then
    report dev_launch_state "$(grep -c '^[a-z]' <<<"$state" || true)"
  elif grep -q 'No state file was found' <<<"$state"; then
    report dev_launch_state 0
  else
    report dev_launch_state error
  fi
else
  report dev_launch_state error
fi

if ((FAIL)); then
  echo "launch_check FAILED: something from the launch is still up, or could not be read"
  exit 1
fi
echo "launch_check ok"
