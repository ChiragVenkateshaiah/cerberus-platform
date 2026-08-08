terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately no `backend "s3" {}` block here. These resources ARE the
  # remote backend every other Terraform config (envs/dev, and future
  # envs/*) points at -- state for this directory can't live in the thing
  # it's describing. This is the standard Terraform bootstrap pattern:
  # state stays local (terraform.tfstate, gitignored) for this one
  # directory only, precisely because it has no chicken to its egg.
}
