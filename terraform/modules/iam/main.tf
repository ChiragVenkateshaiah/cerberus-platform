# Three least-privilege roles per ADR 0002's forward pointer: ingestion
# (write bronze only), transform (read bronze, write silver/gold), serving
# (read gold only). Nothing assumes these automatically yet -- Phase 2's
# Lambda (2.3) and later compute get their own trust policies when they
# exist; for now they're assumable by hand via `aws sts assume-role`,
# trusted_principal_arn is cerberus-admin. Each role's permissions are
# genuinely usable today, ahead of the compute that will eventually hold
# them -- a deliberate head start on repaying Phase 0's AdministratorAccess
# shortcut (fully repaid at 7.3), not a placeholder.
#
# Policies are inline (aws_iam_role_policy), not standalone managed
# policies -- each one is scoped 1:1 to exactly one role and isn't meant to
# be shared or attached elsewhere, so there's no reuse case a standalone
# aws_iam_policy would buy.

locals {
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = var.trusted_principal_arn }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  glue_catalog_arn         = "arn:aws:glue:${var.region}:${var.account_id}:catalog"
  glue_database_arn        = "arn:aws:glue:${var.region}:${var.account_id}:database/${var.glue_database_name}"
  glue_partition_table_arn = "arn:aws:glue:${var.region}:${var.account_id}:table/${var.glue_database_name}/${var.glue_partition_table_name}"
  glue_serving_table_arns  = [for t in var.glue_table_names : "arn:aws:glue:${var.region}:${var.account_id}:table/${var.glue_database_name}/${t}"]
}

# --- Ingestion: write-only, bronze/payments/* ---------------------------

resource "aws_iam_role" "ingestion" {
  name               = "cerberus-ingestion"
  assume_role_policy = local.assume_role_policy
}

resource "aws_iam_role_policy" "ingestion" {
  name = "cerberus-ingestion-policy"
  role = aws_iam_role.ingestion.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WritePaymentsToBronze"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${var.bucket_arns["bronze"]}/payments/*"
      }
    ]
  })
}

# --- Transform: read bronze/payments/*, read+write silver and gold ------

resource "aws_iam_role" "transform" {
  name               = "cerberus-transform"
  assume_role_policy = local.assume_role_policy
}

resource "aws_iam_role_policy" "transform" {
  name = "cerberus-transform-policy"
  role = aws_iam_role.transform.id

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
        Sid    = "ReadWriteSilverAndGold"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${var.bucket_arns["silver"]}/*",
          "${var.bucket_arns["gold"]}/*",
        ]
      },
      {
        Sid    = "ListSilverAndGold"
        Effect = "Allow"
        Action = "s3:ListBucket"
        Resource = [
          var.bucket_arns["silver"],
          var.bucket_arns["gold"],
        ]
      },
      {
        Sid    = "RegisterPaymentsEventsPartitions"
        Effect = "Allow"
        Action = ["glue:GetTable", "glue:BatchCreatePartition", "glue:GetPartitions"]
        Resource = [
          local.glue_catalog_arn,
          local.glue_database_arn,
          local.glue_partition_table_arn,
        ]
      }
    ]
  })
}

# --- Serving: read-only, gold/* -------------------------------------------
# Athena's own query-execution permissions (the query-results bucket, etc.)
# land here once 1.10 actually builds that; this is just catalog + gold
# object read access.

resource "aws_iam_role" "serving" {
  name               = "cerberus-serving"
  assume_role_policy = local.assume_role_policy
}

resource "aws_iam_role_policy" "serving" {
  name = "cerberus-serving-policy"
  role = aws_iam_role.serving.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadGold"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${var.bucket_arns["gold"]}/*"
      },
      {
        Sid      = "ListGold"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.bucket_arns["gold"]
      },
      {
        Sid    = "ReadPaymentsCatalog"
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
        Resource = concat(
          [local.glue_catalog_arn, local.glue_database_arn],
          local.glue_serving_table_arns,
        )
      }
    ]
  })
}
