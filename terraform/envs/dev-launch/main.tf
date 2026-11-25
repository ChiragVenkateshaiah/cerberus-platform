# 17.3b (ADR 0030): the fourth root. The per-session launch edge, human-run
# from the owner's terminal, never planned or applied by CI. No secret is
# anywhere in this root: the signing key is public, and the private key and
# the cookies live only in the session (tmpfs, then an SSM parameter created
# outside Terraform).

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# Reads envs/dev-standing's applied outputs, one-directional.
data "terraform_remote_state" "standing" {
  backend = "s3"

  config = {
    bucket = "cerberus-platform-tfstate-${data.aws_caller_identity.current.account_id}"
    key    = "envs/dev-standing/terraform.tfstate"
    region = "us-east-1"
  }
}

locals {
  standing = data.terraform_remote_state.standing.outputs
}

module "launch_edge" {
  source = "../../modules/launch_edge"

  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name

  public_key_pem   = var.public_key_pem
  release_at_epoch = var.release_at_epoch

  create_load_gen         = var.create_load_gen
  vpc_id                  = local.standing.vpc_id
  subnet_id               = local.standing.public_subnet_a_id
  minutes                 = var.minutes
  shutdown_margin_minutes = var.shutdown_margin_minutes
  instance_type           = var.instance_type
  k6_version              = var.k6_version
  k6_sha256               = var.k6_sha256
}
