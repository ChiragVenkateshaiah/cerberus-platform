provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project = "cerberus-platform"
    }
  }
}

data "aws_caller_identity" "current" {}

# ADR 0011 (5.1): reads envs/dev-standing's already-applied outputs --
# vpc_id, private_subnet_ids, public_subnet_a_id, private_route_table_id,
# orchestration_transform_role_arn, bucket_arns -- one-directional
# (compute depends on standing, never the reverse). Standing must exist
# before this root is ever applied, which is naturally true: it's CI's
# continuous baseline, and this root only spins up compute on top of it
# for an exercise.
data "terraform_remote_state" "standing" {
  backend = "s3"

  config = {
    bucket = "cerberus-platform-tfstate-131715059025"
    key    = "envs/dev-standing/terraform.tfstate"
    region = "us-east-1"
  }
}

# 3.4: authenticates the kubernetes/helm providers against the EKS cluster
# built by module.eks below. Both providers' config depends on module.eks's
# outputs, so they only resolve once the cluster exists -- this root's
# modules are meant to apply in one run, not separately (see
# checkpoint.md's Notes/blockers: one apply exercising the whole compute
# stack, not a standing idle cluster).

data "aws_eks_cluster_auth" "this" {
  name = module.eks.cluster_name
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}
