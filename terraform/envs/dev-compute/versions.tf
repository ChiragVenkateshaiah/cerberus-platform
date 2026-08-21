terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # 3.2: fetches the EKS cluster's OIDC issuer certificate thumbprint for
    # the IAM OIDC provider (terraform/modules/eks) -- no other module
    # needs it.
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    # 3.4: talks to the EKS cluster's API server -- kubernetes for the
    # spark-operator/spark-jobs namespaces, helm for the operator's chart
    # install (terraform/modules/spark_operator). Both authenticate via
    # data.aws_eks_cluster_auth in provider.tf.
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.31"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.14"
    }
  }

  # No `profile` -- this root is human-run only (never CI, per ADR 0011),
  # but kept consistent with envs/dev-standing's env-var-based auth anyway
  # rather than reintroducing a hardcoded identity. Export
  # AWS_PROFILE=cerberus-admin before running terraform here.
  backend "s3" {
    bucket         = "cerberus-platform-tfstate-131715059025"
    key            = "envs/dev-compute/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "cerberus-platform-tfstate-lock"
    encrypt        = true
  }
}
