terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # 2.1: zips the ingestion Lambda's code and Faker layer at apply time
    # (terraform/modules/lambda_ingestion) -- no other module needs it.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    # 3.2: fetches the EKS cluster's OIDC issuer certificate thumbprint for
    # the IAM OIDC provider (terraform/modules/eks) -- no other module
    # needs it.
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    bucket         = "cerberus-platform-tfstate-131715059025"
    key            = "envs/dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "cerberus-platform-tfstate-lock"
    encrypt        = true
    profile        = "cerberus-admin"
  }
}
