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
# Read bronze/payments/*, write silver (and, since 8.3, bronze/payments_bulk/*
# for the bulk generator, ADR 0018). It never touches gold: the job is only
# the bronze -> silver step. Until 8.5 it had no Glue permissions at all
# (an MSCK REPAIR run as cerberus-transform registered silver's partitions).
# Since 8.5 silver is an Iceberg table whose commits go through the Glue
# catalog, so the role has Glue read/create/update on that one table
# (ADR 0017) -- and still nothing else in Glue.

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

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
        # 8.3 (ADR 0018): the bulk generator writes JSON Lines here. Delete
        # is for the committer's staging files and for a same-run_id re-run;
        # nothing outside payments_bulk/ gains write or delete. The bare
        # payments_bulk key is listed too: S3A probes the output root as a
        # file before it writes, and without a grant on that exact key S3
        # answers 403 instead of 404 (checked live 2026-10-07 against
        # cerberus-transform's same prefix-scoped shape).
        Sid    = "WriteBronzePaymentsBulk"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
        Resource = [
          "${var.bucket_arns["bronze"]}/payments_bulk",
          "${var.bucket_arns["bronze"]}/payments_bulk/*",
        ]
      },
      {
        Sid      = "ListBronzePaymentsPrefixOnly"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.bucket_arns["bronze"]
        Condition = {
          StringLike = { "s3:prefix" = ["payments/*", "payments_bulk", "payments_bulk/*"] }
        }
      },
      {
        # AbortMultipartUpload (8.5): Iceberg's S3FileIO writes large data
        # files as multipart uploads and aborts them on a failed task.
        Sid      = "WriteSilver"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
        Resource = "${var.bucket_arns["silver"]}/*"
      },
      {
        Sid      = "ListSilver"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.bucket_arns["silver"]
      },
      {
        # 8.5 (ADR 0017): Iceberg's Glue catalog commits each silver write by
        # updating the table's metadata pointer in Glue, so the job needs
        # table read/create/update -- scoped to the one silver table. No
        # DeleteTable: the Hive table it replaces is dropped by Terraform
        # (dev-standing), not by the job.
        Sid    = "IcebergSilverCatalog"
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetTable", "glue:CreateTable", "glue:UpdateTable"]
        Resource = [
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:database/${var.glue_database_name}",
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${var.glue_database_name}/${var.silver_table_name}",
        ]
      }
    ]
  })
}
