# ADR 0020 (8.8): Cluster Autoscaler for dev-compute's Spot executor node
# group. The executor group starts at, and never drops below, the size an
# exercise asks for (eks.executor_desired_size), so the job doesn't wait on
# a scale-up; this covers what can't be planned: growing when Spark's
# dynamic allocation asks for executors that don't fit, and shrinking back
# to the planned size once they're gone. (The Auto Scaling group itself
# replaces an interrupted Spot node, to keep its minimum.)
#
# Auto-discovery: EKS tags every managed node group's Auto Scaling group
# with k8s.io/cluster-autoscaler/enabled and
# k8s.io/cluster-autoscaler/<cluster>. To scale the executor group up from
# zero, the autoscaler reads the group's labels and taint from
# eks:DescribeNodegroup -- no node-template tags to maintain on an Auto
# Scaling group Terraform doesn't own.
#
# Applied only from envs/dev-compute, like iam_spark and eks_observability:
# the IRSA role federates through the per-exercise cluster's OIDC provider.

locals {
  oidc_issuer_host = replace(var.eks_oidc_issuer_url, "https://", "")
  service_account  = "cluster-autoscaler"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Named cerberus-* because cerberus-admin's role management is scoped to
# that prefix (iam/cerberus-admin/policies, IamRoleMgmt).
resource "aws_iam_role" "autoscaler" {
  name = "cerberus-cluster-autoscaler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = var.eks_oidc_provider_arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_issuer_host}:sub" = "system:serviceaccount:${var.namespace}:${local.service_account}"
            "${local.oidc_issuer_host}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = {
    Phase     = "8"
    Component = "cluster-autoscaler"
  }
}

# The autoscaler's documented AWS policy, with the two write actions scoped
# to this cluster's own Auto Scaling groups by the tag EKS puts on them.
resource "aws_iam_role_policy" "autoscaler" {
  name = "cerberus-cluster-autoscaler-policy"
  role = aws_iam_role.autoscaler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Discover"
        Effect = "Allow"
        Action = [
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:DescribeScalingActivities",
          "autoscaling:DescribeTags",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:GetInstanceTypesFromInstanceRequirements",
        ]
        Resource = "*"
      },
      {
        # Labels and taints of a node group at zero nodes.
        Sid      = "DescribeNodegroups"
        Effect   = "Allow"
        Action   = "eks:DescribeNodegroup"
        Resource = "arn:aws:eks:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:nodegroup/${var.cluster_name}/*/*"
      },
      {
        Sid    = "ScaleOwnGroups"
        Effect = "Allow"
        Action = [
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/k8s.io/cluster-autoscaler/${var.cluster_name}" = "owned"
          }
        }
      },
    ]
  })
}

resource "helm_release" "autoscaler" {
  name       = "cluster-autoscaler"
  repository = "https://kubernetes.github.io/autoscaler"
  chart      = "cluster-autoscaler"
  version    = var.chart_version
  namespace  = var.namespace

  values = [yamlencode({
    cloudProvider = "aws"
    awsRegion     = data.aws_region.current.name
    autoDiscovery = { clusterName = var.cluster_name }

    # The autoscaler's minor version must match the cluster's. The cluster
    # takes AWS's default Kubernetes version at apply time (eks module), so
    # the tag follows it instead of the chart's own default.
    image = { tag = "v${var.kubernetes_version}.0" }

    rbac = {
      serviceAccount = {
        name        = local.service_account
        annotations = { "eks.amazonaws.com/role-arn" = aws_iam_role.autoscaler.arn }
      }
    }

    extraArgs = {
      # A one-job cluster: give back an extra Spot node 2 minutes after it
      # empties, not the default 10. The planned nodes are the group's
      # minimum, so this never removes them.
      "scale-down-unneeded-time"   = "2m"
      "scale-down-delay-after-add" = "2m"
      # Spot executor groups use several same-size types (ADR 0020).
      "balance-similar-node-groups" = "true"
      "expander"                    = "least-waste"
    }
  })]
}
