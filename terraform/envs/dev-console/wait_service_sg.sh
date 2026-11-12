#!/usr/bin/env bash
# Wait until the number of CloudFront-VPCOrigins-Service-SG groups in the VPC
# equals WANT (spike finding 1: the VPC origin's create call can return before
# CloudFront has made the group; and an old session's group lingers a few
# minutes after its origin is deleted).
#   WANT=0  before the VPC origin: wait for a stale group to go away.
#   WANT=1  after the VPC origin: wait for the new group. More than one group
#           is an error at once (the data source could not pick one).
# Read-only: one ec2:DescribeSecurityGroups call every 10 seconds. Run by the
# terraform_data local-exec resources in edge.tf, which set VPC_ID, WANT,
# AWS_REGION and MAX_SECONDS; AWS_PROFILE comes from the owner's shell.
set -euo pipefail

: "${VPC_ID:?VPC_ID is not set}"
: "${WANT:?WANT is not set (0 or 1)}"
: "${MAX_SECONDS:=600}"
case "$WANT" in 0 | 1) ;; *)
  echo "WANT must be 0 or 1" >&2
  exit 2
  ;;
esac

deadline=$((SECONDS + MAX_SECONDS))
while true; do
  found="$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    "Name=group-name,Values=CloudFront-VPCOrigins-Service-SG*" \
    "Name=tag-key,Values=aws.cloudfront.vpcorigin" \
    --query 'length(SecurityGroups)' --output text || echo -1)"
  if [ "$found" = "$WANT" ]; then
    echo "service SG count is $found"
    exit 0
  fi
  if [ "$WANT" = "1" ] && [ "$found" -gt 1 ] 2> /dev/null; then
    echo "found $found service SGs, expected 1" >&2
    exit 1
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "service SG count is $found, wanted $WANT, after ${MAX_SECONDS}s" >&2
    exit 1
  fi
  sleep 10
done
