# No `profile`: same reasoning as envs/dev-standing/provider.tf. Export
# AWS_PROFILE=cerberus-admin before running terraform.
#
# The Project tag is required: the cerberus-admin CloudFront and EC2 grants
# carry aws:RequestTag / aws:ResourceTag conditions on it. Stack lets
# console_check.sh (PR E) find everything this root creates.
provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project = "cerberus-platform"
      Stack   = "dev-console"
    }
  }
}
