# EKS cluster module (3.2), built against ADR 0007's VPC design: worker
# nodes in the private subnets, no direct inbound path; the control plane's
# API endpoint stays public -- a real, accepted gap (no bastion/VPN in this
# solo project), not an oversight. Spin-up/destroy pattern (3.7), not
# standing infrastructure -- this is the first component in the platform
# where that discipline matters, since the control plane alone bills
# regardless of load.

# --- Cluster IAM role -----------------------------------------------------

resource "aws_iam_role" "cluster" {
  name = "cerberus-platform-eks-cluster"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "eks.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = { Phase = "3" }
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# --- Node group IAM role ---------------------------------------------------

resource "aws_iam_role" "node" {
  name = "cerberus-platform-eks-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = { Phase = "3" }
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ])

  role       = aws_iam_role.node.name
  policy_arn = each.value
}

# --- Cluster ---------------------------------------------------------------

resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_public_access  = true
    endpoint_private_access = false
  }

  # No bastion/VPN in this solo project (ADR 0007's Security row) -- the
  # applying identity (cerberus-admin) gets cluster-admin access directly
  # rather than through a hand-built aws_eks_access_entry.
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  tags = { Phase = "3" }

  depends_on = [
    aws_iam_role_policy_attachment.cluster,
  ]
}

# --- Node group --------------------------------------------------------------

resource "aws_eks_node_group" "this" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "cerberus-platform-eks-nodes"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids

  capacity_type  = "ON_DEMAND"
  instance_types = var.node_instance_types

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  tags = { Phase = "3" }

  depends_on = [
    aws_iam_role_policy_attachment.node,
  ]
}

# --- OIDC provider: cluster-level primitive enabling IRSA (IAM Roles for
# Service Accounts), so 3.4/3.5 can scope Spark's own S3 access to a
# service-account-bound role instead of the broad node role above -- built
# here since the provider is 1:1 with the cluster; the Spark-specific role
# itself is 3.4/3.5's job, not this module's.

data "tls_certificate" "eks_oidc" {
  url = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks_oidc.certificates[0].sha1_fingerprint]

  tags = { Phase = "3" }
}

# NB (4.2): the access entry for cerberus-orchestration-transform's IAM
# role deliberately does NOT live here, even though this module owns
# every other cluster-level access concern. This module's own
# oidc_provider_arn/oidc_issuer_url outputs feed module.iam's cerberus-spark
# trust policy -- iam already depends on eks. An access entry here would
# need module.iam's orchestration_transform role ARN, making eks depend on
# iam right back -- a real module cycle, not a hypothetical one. It lives
# in terraform/modules/spark_job instead, alongside the RBAC
# role/binding that grants that same principal's actual permissions --
# spark_job already depends on both modules with no reverse edge.
