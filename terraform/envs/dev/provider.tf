provider "aws" {
  region  = "us-east-1"
  profile = "cerberus-admin"

  default_tags {
    tags = {
      Project = "cerberus-platform"
    }
  }
}

data "aws_caller_identity" "current" {}
