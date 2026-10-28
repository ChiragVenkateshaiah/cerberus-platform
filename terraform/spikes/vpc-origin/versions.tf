terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # No backend block, on purpose: this is a throwaway spike (9.2, ADR 0024
  # build step 3). State is local, the root is human-run (or run by the main
  # Claude session with the user's OK) and never planned or applied in CI.
  # The repo's S3 backend bucket name contains the account ID, and a new
  # committed file must not carry it. Deleted in the step 10 PR.
}
