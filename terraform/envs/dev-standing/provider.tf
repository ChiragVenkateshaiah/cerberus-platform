# ADR 0011 (5.1): no hardcoded `profile` here, unlike the old envs/dev.
# This root is now applied from two different identities -- a human
# locally (via the AWS_PROFILE=cerberus-admin env var, not an HCL
# literal) and GitHub Actions in CI (via OIDC-assumed credentials injected
# as env vars by aws-actions/configure-aws-credentials). A hardcoded
# `profile` would make the provider look for a `cerberus-admin` entry in
# ~/.aws/credentials that simply doesn't exist on a GitHub-hosted runner,
# breaking CI outright. The AWS provider's default credential chain
# (env vars, then profile, then instance/task metadata) resolves correctly
# either way without this file needing to know which caller it is.
provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project = "cerberus-platform"
    }
  }
}

data "aws_caller_identity" "current" {}
