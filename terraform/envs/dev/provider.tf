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

# 3.4: authenticates the kubernetes/helm providers against the EKS cluster
# built in 3.2. Both providers' config depends on module.eks's outputs, so
# they only resolve once the cluster exists -- this module + the spark_operator
# module are meant to apply in the same run as 3.2's VPC/EKS stack, not
# separately (see checkpoint.md's Next up: one apply exercising the whole
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
