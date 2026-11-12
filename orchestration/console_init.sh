#!/usr/bin/env bash
# terraform init for envs/dev-console, shared by `make console-plan`,
# console_check.sh and console_session.sh so they all use the same backend.
#
# dev-console has a partial S3 backend: the state bucket name holds the
# account ID, which a committed file must not. The account ID comes from one
# sts:GetCallerIdentity call (read-only) and goes to terraform as
# -backend-config flags. This script does not echo it; terraform's own error
# text can name the bucket, so do not paste that output into a public place.
#
# Usage: console_init.sh [extra terraform init flags]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF="${TF_BIN:-terraform}"
export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="${AWS_REGION:-us-east-1}"

acct="$(aws sts get-caller-identity --query Account --output text)"
exec "$TF" -chdir="$REPO/terraform/envs/dev-console" init -input=false \
  -backend-config="bucket=cerberus-platform-tfstate-$acct" \
  -backend-config="key=envs/dev-console/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=cerberus-platform-tfstate-lock" \
  -backend-config="encrypt=true" \
  "$@"
