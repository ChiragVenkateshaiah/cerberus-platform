terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # The session bundle (observability/grafana/console + dashboards + run
    # records) is zipped here; see session.tf.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    # time_static records when the session went live, once, so `started` and
    # `ends` in live.json do not change on every plan.
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # Partial backend, on purpose: the state bucket's name contains the account
  # ID, and a new committed file must not carry it (plan 2026-11-12 §3; the
  # older roots predate that rule). `make console-plan` fills it in:
  #
  #   terraform init \
  #     -backend-config="bucket=cerberus-platform-tfstate-<account-id>" \
  #     -backend-config="key=envs/dev-console/terraform.tfstate" \
  #     -backend-config="region=us-east-1" \
  #     -backend-config="dynamodb_table=cerberus-platform-tfstate-lock" \
  #     -backend-config="encrypt=true"
  #
  # Table, region and the bucket name pattern are the values in
  # envs/dev-compute/versions.tf. Human-run only (never CI, ADR 0011). No
  # `profile`: export AWS_PROFILE=cerberus-admin before running terraform here.
  backend "s3" {}
}
