terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # 2.1: zips the ingestion Lambda's code and Faker layer at apply time
    # (terraform/modules/lambda_ingestion) -- no other module in this root
    # needs it.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    # 5.1: fetches token.actions.githubusercontent.com's certificate
    # thumbprint for the GitHub OIDC provider (terraform/modules/
    # github_oidc) -- same pattern envs/dev-compute's eks module already
    # uses for EKS's own OIDC provider.
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # No `profile` here either -- same reasoning as provider.tf. Locally,
  # export AWS_PROFILE=cerberus-admin before running terraform; CI's
  # workflow sets AWS_* env vars via aws-actions/configure-aws-credentials.
  backend "s3" {
    bucket         = "cerberus-platform-tfstate-131715059025"
    key            = "envs/dev-standing/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "cerberus-platform-tfstate-lock"
    encrypt        = true
  }
}
