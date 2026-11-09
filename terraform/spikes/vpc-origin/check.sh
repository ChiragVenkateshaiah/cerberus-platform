#!/usr/bin/env bash
set -euo pipefail

# 9.2 VPC-origin spike -- read-only state check. Prints `key value` lines.
# Changes nothing in AWS (describe/list/get calls only).
#
#   check.sh
#   check.sh --watch-enis INTERVAL MAX
#
#   --watch-enis INTERVAL MAX
#                 after the checks, poll every INTERVAL seconds until the
#                 VPC has 0 network interfaces, printing the elapsed seconds.
#                 Gives up after MAX seconds (exit 1). The CloudFront service
#                 ENIs can outlive the VPC origin by a few minutes.
#
# Uses AWS_PROFILE / AWS_REGION from the environment (defaults below).

export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_PAGER=""

SPIKE_NAME="cerberus-vpc-origin-spike"
ROLE_NAME="cerberus-console-grafana-spike"
VPC_NAME="cerberus-platform-vpc"

WATCH=false INTERVAL="" MAX=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --watch-enis)
      [[ $# -ge 3 ]] || { echo "--watch-enis needs INTERVAL and MAX" >&2; exit 2; }
      [[ "$2$3" =~ ^[0-9]+$ ]] || { echo "INTERVAL and MAX must be integers" >&2; exit 2; }
      WATCH=true INTERVAL="$2" MAX="$3"
      shift 2
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

show() { printf '%s %s\n' "$1" "$2"; }

# 1 if the IAM entity exists, 0 if NoSuchEntity. Any other error is shown as
# "error", so a denied read is never reported as a clean 0.
iam_exists() {
  local out
  if out="$("$@" 2>&1)"; then
    echo 1
  elif grep -q NoSuchEntity <<<"$out"; then
    echo 0
  else
    echo error
  fi
}

vpc_id="$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=$VPC_NAME" \
  --query 'Vpcs[0].VpcId' --output text)"
if [[ "$vpc_id" == "None" || -z "$vpc_id" ]]; then
  echo "STOP: VPC $VPC_NAME not found" >&2
  exit 1
fi

vpc_enis() {
  aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$vpc_id" \
    --query 'length(NetworkInterfaces)' --output text
}

# The four counts exercise.sh checks after a destroy.
show eks_clusters "$(aws eks list-clusters --query 'length(clusters)' --output text)"
show nat_pending_available "$(aws ec2 describe-nat-gateways \
  --filter Name=state,Values=pending,available --query 'length(NatGateways)' --output text)"
show eips "$(aws ec2 describe-addresses --query 'length(Addresses)' --output text)"
show running_instances "$(aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=pending,running \
  --query 'length(Reservations[].Instances[])' --output text)"

# CloudFront. (Backticks below are JMESPath literals, not shell.)
# shellcheck disable=SC2016
show distributions "$(aws cloudfront list-distributions \
  --query 'length(DistributionList.Items || `[]`)' --output text)"
# shellcheck disable=SC2016
show vpc_origins "$(aws cloudfront list-vpc-origins \
  --query 'length(VpcOriginList.Items || `[]`)' --output text)"

# Spike instance (any state but terminated or shutting-down).
show spike_instances_not_terminated "$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$SPIKE_NAME" \
  Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'length(Reservations[].Instances[])' --output text)"
show spike_instance_public_ip "$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$SPIKE_NAME" \
  Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
show spike_instance_http_tokens "$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$SPIKE_NAME" \
  Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[0].Instances[0].MetadataOptions.HttpTokens' --output text)"

# Security groups.
spike_sg="$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$vpc_id" "Name=group-name,Values=$SPIKE_NAME" \
  --query 'SecurityGroups[0].GroupId' --output text)"
service_sg="$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$vpc_id" "Name=group-name,Values=CloudFront-VPCOrigins-Service-SG*" \
  --query 'SecurityGroups[0].GroupId' --output text)"

if [[ "$spike_sg" == "None" ]]; then
  show spike_sg 0
else
  show spike_sg 1
  show spike_sg_ingress_rules "$(aws ec2 describe-security-groups --group-ids "$spike_sg" \
    --query 'length(SecurityGroups[0].IpPermissions)' --output text)"
  show spike_sg_egress_rules "$(aws ec2 describe-security-groups --group-ids "$spike_sg" \
    --query 'length(SecurityGroups[0].IpPermissionsEgress)' --output text)"
  show spike_sg_ingress "$(aws ec2 describe-security-groups --group-ids "$spike_sg" \
    --query 'SecurityGroups[0].IpPermissions[].[IpProtocol,FromPort,ToPort,length(UserIdGroupPairs)]' \
    --output text | tr '\t' ':' | paste -sd, -)"
  from_service="$(aws ec2 describe-security-groups --group-ids "$spike_sg" \
    --query 'SecurityGroups[0].IpPermissions[].UserIdGroupPairs[].GroupId' --output text)"
  if [[ "$service_sg" != "None" && " ${from_service//$'\t'/ } " == *" $service_sg "* ]]; then
    show spike_sg_ingress_from_service_sg yes
  else
    show spike_sg_ingress_from_service_sg no
  fi
fi

if [[ "$service_sg" == "None" ]]; then
  show service_sg 0
else
  show service_sg 1
  show service_sg_ingress_rules "$(aws ec2 describe-security-groups --group-ids "$service_sg" \
    --query 'length(SecurityGroups[0].IpPermissions)' --output text)"
  show service_sg_egress_rules "$(aws ec2 describe-security-groups --group-ids "$service_sg" \
    --query 'length(SecurityGroups[0].IpPermissionsEgress)' --output text)"
fi

# ENIs in the VPC, with a breakdown by InterfaceType and Description.
show vpc_enis "$(vpc_enis)"
aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$vpc_id" \
  --query 'NetworkInterfaces[].[InterfaceType,Description]' --output text |
  sort | uniq -c | sed 's/^ *\([0-9]*\) /vpc_eni_group \1 /'

# IAM.
show role "$(iam_exists aws iam get-role --role-name "$ROLE_NAME")"
show instance_profile "$(iam_exists aws iam get-instance-profile --instance-profile-name "$ROLE_NAME")"

if $WATCH; then
  start=$SECONDS
  while :; do
    n="$(vpc_enis)"
    elapsed=$((SECONDS - start))
    show eni_watch "elapsed=${elapsed}s enis=$n"
    [[ "$n" == "0" ]] && exit 0
    if ((elapsed + INTERVAL > MAX)); then
      show eni_watch_gave_up "after=${elapsed}s enis=$n"
      exit 1
    fi
    sleep "$INTERVAL"
  done
fi
