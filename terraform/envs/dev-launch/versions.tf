terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Partial backend, on purpose: the state bucket's name contains the account
  # ID, and a committed file must not carry it. `make launch-plan` fills it in
  # through orchestration/launch_init.sh:
  #
  #   terraform init \
  #     -backend-config="bucket=cerberus-platform-tfstate-<account-id>" \
  #     -backend-config="key=envs/dev-launch/terraform.tfstate" \
  #     -backend-config="region=us-east-1" \
  #     -backend-config="dynamodb_table=cerberus-platform-tfstate-lock" \
  #     -backend-config="encrypt=true"
  #
  # Human-run only (never CI, ADR 0011 as amended by ADR 0030). No `profile`:
  # export AWS_PROFILE=cerberus-admin before running terraform here.
  backend "s3" {}
}
