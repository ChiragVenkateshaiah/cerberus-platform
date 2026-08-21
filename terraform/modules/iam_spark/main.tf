# cerberus-spark (3.5), split out of terraform/modules/iam by ADR 0011
# (5.1): the only IAM role whose trust policy depends entirely on the EKS
# OIDC provider (IRSA federation from an EKS service account, rather than
# either sts:AssumeRole or a service principal -- Spark's driver/executor
# pods get temporary credentials scoped to exactly one namespaced service
# account, not the cluster's whole node role). That makes it
# lifecycle-coupled to eks/spark_operator/spark_job, not to the standing
# roles in terraform/modules/iam -- this module is applied only from
# envs/dev-compute, alongside those three, never by CI.
#
# Read bronze/payments/*, write silver only -- S3 only, no Glue. Narrower
# than cerberus-transform in two ways: this job replaces only the bronze ->
# silver step (flatten/parse), not the gold rollup, so it has no reason to
# touch gold; and it doesn't register silver's new partitions with Glue
# itself (the off-the-shelf Spark image has no boto3), so it needs no Glue
# permissions at all -- transform/spark/submit_job.sh does that step
# afterward via cerberus-transform's existing Glue/Athena grant instead.

locals {
  # OIDC issuer URL without its https:// scheme -- how it appears as the
  # Condition key prefix in an IRSA trust policy.
  oidc_issuer_host = replace(var.eks_oidc_issuer_url, "https://", "")
}

resource "aws_iam_role" "spark" {
  name = "cerberus-spark"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = var.eks_oidc_provider_arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_issuer_host}:sub" = "system:serviceaccount:${var.spark_service_account}"
            "${local.oidc_issuer_host}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "spark" {
  name = "cerberus-spark-policy"
  role = aws_iam_role.spark.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadBronzePayments"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${var.bucket_arns["bronze"]}/payments/*"
      },
      {
        Sid      = "ListBronzePaymentsPrefixOnly"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.bucket_arns["bronze"]
        Condition = {
          StringLike = { "s3:prefix" = ["payments/*"] }
        }
      },
      {
        Sid      = "WriteSilver"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${var.bucket_arns["silver"]}/*"
      },
      {
        Sid      = "ListSilver"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.bucket_arns["silver"]
      }
    ]
  })
}
