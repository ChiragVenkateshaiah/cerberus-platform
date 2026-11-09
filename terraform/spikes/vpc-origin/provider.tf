# No `profile`: same reasoning as terraform/envs/dev-standing/provider.tf.
# Export AWS_PROFILE=cerberus-admin before running terraform.
#
# The Project tag is required: the cerberus-admin CloudFront and EC2 grants
# carry aws:RequestTag / aws:ResourceTag conditions on it.
provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project = "cerberus-platform"
    }
  }
}
