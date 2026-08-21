# Three human-assumable, least-privilege roles per ADR 0002's forward
# pointer: ingestion (write bronze only), transform (read bronze, write
# silver/gold), serving (read gold only) -- assumable by hand via
# `aws sts assume-role`, trusted_principal_arn is cerberus-admin. Each
# role's permissions are genuinely usable today, ahead of the compute that
# will eventually hold them -- a deliberate head start on repaying Phase 0's
# AdministratorAccess shortcut (fully repaid at 7.3), not a placeholder.
# A fourth role, ingestion_lambda, is the first of these actually assumed
# by compute rather than a human (2.1/2.3, ADR 0005) -- see below.
#
# cerberus-spark (3.5), the IRSA-federated role Spark's driver/executor
# pods assume, does NOT live in this module -- it moved to
# terraform/modules/iam_spark by ADR 0011 (5.1). It's the one role whose
# whole trust policy depends on the EKS OIDC provider, so it's
# lifecycle-coupled to eks/spark_operator/spark_job rather than to any of
# the standing roles below; all four live together in envs/dev-compute,
# outside CI's blast radius. See iam_spark/main.tf for the role itself.
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

  # dbt (1.9) creates and owns these tables -- scoped by name prefix so
  # cerberus-transform gets DDL rights only over tables it creates, not
  # payments_events/payments_current (those stay Terraform-owned via 1.8).
  glue_dbt_fct_table_arn = "arn:aws:glue:${var.region}:${var.account_id}:table/${var.glue_database_name}/fct_*"
  glue_dbt_dim_table_arn = "arn:aws:glue:${var.region}:${var.account_id}:table/${var.glue_database_name}/dim_*"

  athena_workgroup_arn = "arn:aws:athena:${var.region}:${var.account_id}:workgroup/${var.athena_workgroup_name}"

  eks_cluster_arn = "arn:aws:eks:${var.region}:${var.account_id}:cluster/${var.eks_cluster_name}"
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

# --- Ingestion Lambda: same write-only scope as cerberus-ingestion, but --
# trusted by lambda.amazonaws.com instead of a human principal (2.1/2.3,
# ADR 0005). Kept as its own role rather than extending cerberus-ingestion's
# trust policy: Lambda has no CLI-style profile-chaining equivalent to
# ~/.aws/config's role_arn/source_profile, so reusing cerberus-ingestion
# would mean the handler calling sts:AssumeRole explicitly in code for no
# benefit over a role scoped identically from the start.

resource "aws_iam_role" "ingestion_lambda" {
  name = "cerberus-ingestion-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "ingestion_lambda" {
  name = "cerberus-ingestion-lambda-policy"
  role = aws_iam_role.ingestion_lambda.id

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

# AWS-managed, not inline: this is boilerplate CloudWatch Logs access every
# Lambda needs (CreateLogGroup/CreateLogStream/PutLogEvents), not a
# project-specific data-plane grant -- the one deliberate exception to this
# module's "inline only" convention above, which is about not standing up a
# redundant aws_iam_policy for a 1:1 grant, not about avoiding AWS's own
# managed policies for standard runtime plumbing.
resource "aws_iam_role_policy_attachment" "ingestion_lambda_logs" {
  role       = aws_iam_role.ingestion_lambda.id
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
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
        # DeleteObject: dbt-athena clears a table's target location before
        # every CTAS run (not just full-refresh), same "full rebuild each
        # run" idempotency 1.7's own transform already relies on.
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
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
      },
      {
        Sid    = "ManageDbtGoldTables"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:DeleteTable",
          "glue:BatchCreatePartition",
          "glue:GetPartitions",
          "glue:BatchDeletePartition",
        ]
        Resource = [
          local.glue_catalog_arn,
          local.glue_database_arn,
          local.glue_dbt_fct_table_arn,
          local.glue_dbt_dim_table_arn,
        ]
      },
      {
        Sid      = "RunAthenaQueries"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"]
        Resource = local.athena_workgroup_arn
      },
      {
        Sid      = "WriteAthenaResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${var.athena_results_bucket_arn}/*"
      },
      {
        Sid      = "ListAthenaResults"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = var.athena_results_bucket_arn
      }
    ]
  })
}

# --- Orchestration (4.2): three roles for the ECS Fargate tasks and the --
# state machine itself. Two carry their full inline policy here, matching
# every other role in this module; the third (orchestration_state_machine)
# gets its trust policy here but its inline policy in
# terraform/modules/step_functions -- see that module's main.tf header for
# why (breaking a module dependency cycle on the ECS task-definition ARNs
# it needs, which don't exist until after this module's task roles do).

# cerberus-orchestration-transform: what submit_job.sh (3.5/3.6) already
# does by hand -- upload the Spark script, run MSCK REPAIR TABLE -- plus
# eks:DescribeCluster for the in-container `aws eks update-kubeconfig`
# step. Deliberately narrower than cerberus-transform: no bronze/gold
# access, since this task never touches either.

resource "aws_iam_role" "orchestration_transform" {
  name = "cerberus-orchestration-transform"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "orchestration_transform" {
  name = "cerberus-orchestration-transform-policy"
  role = aws_iam_role.orchestration_transform.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "UploadSparkScriptToSilver"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${var.bucket_arns["silver"]}/_spark_jobs/*"
      },
      {
        # Added 2026-08-20 after a second real, live MSCK REPAIR TABLE
        # failure (generic Hive DDLTask error, no AccessDenied this time)
        # -- once the glue:GetDatabase gap below was fixed, MSCK REPAIR
        # got far enough to actually try scanning the table's S3 data
        # location to discover partitions, which this role had never been
        # granted at all: UploadSparkScriptToSilver above is write-only,
        # scoped to _spark_jobs/*, not payments/*. cerberus-transform (the
        # role this one's policy shape was copied from) has this
        # incidentally via its own ReadWriteSilverAndGold/ListSilverAndGold
        # statements; this role needs it explicitly.
        Sid      = "ReadSilverPaymentsForRepair"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${var.bucket_arns["silver"]}/payments/*"
      },
      {
        Sid      = "ListSilverPaymentsPrefixOnly"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.bucket_arns["silver"]
        Condition = {
          StringLike = { "s3:prefix" = ["payments/*"] }
        }
      },
      {
        # glue:GetDatabase added 2026-08-20 after a real, live
        # MSCK REPAIR TABLE AccessDeniedException -- Athena resolves the
        # database before the table when running that statement, and
        # cerberus-transform (the human-assumed role this containerized
        # task's policy shape was copied from) only avoids needing this
        # explicitly because its separate ManageDbtGoldTables statement
        # happens to grant glue:GetDatabase on the same catalog/database
        # resources too. This role has no dbt-table statement to
        # piggyback on, so it needs the grant here directly.
        Sid    = "RegisterPaymentsEventsPartitions"
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetTable", "glue:BatchCreatePartition", "glue:GetPartitions"]
        Resource = [
          local.glue_catalog_arn,
          local.glue_database_arn,
          local.glue_partition_table_arn,
        ]
      },
      {
        Sid      = "RunAthenaQueries"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"]
        Resource = local.athena_workgroup_arn
      },
      {
        Sid      = "WriteAthenaResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${var.athena_results_bucket_arn}/*"
      },
      {
        Sid      = "ListAthenaResults"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = var.athena_results_bucket_arn
      },
      {
        Sid      = "DescribeClusterForKubeconfig"
        Effect   = "Allow"
        Action   = "eks:DescribeCluster"
        Resource = local.eks_cluster_arn
      }
    ]
  })
}

# cerberus-orchestration-dbt: the Athena/Glue/S3 subset of
# cerberus-transform's policy that covers dbt's actual DDL surface -- no
# bronze/silver access, no partition registration; dbt only ever touches
# gold.

resource "aws_iam_role" "orchestration_dbt" {
  name = "cerberus-orchestration-dbt"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "orchestration_dbt" {
  name = "cerberus-orchestration-dbt-policy"
  role = aws_iam_role.orchestration_dbt.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManageDbtGoldTables"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:DeleteTable",
          "glue:BatchCreatePartition",
          "glue:GetPartitions",
          "glue:BatchDeletePartition",
        ]
        Resource = [
          local.glue_catalog_arn,
          local.glue_database_arn,
          local.glue_dbt_fct_table_arn,
          local.glue_dbt_dim_table_arn,
        ]
      },
      {
        # Added 2026-08-20 after a real, live dbt TABLE_NOT_FOUND error --
        # dim_merchants/dim_customers/fct_transactions all SELECT FROM
        # payments_events as a dbt *source* (models/sources.yml), not
        # something this role creates, so the ManageDbtGoldTables
        # statement above (scoped to fct_*/dim_* only) never covered it.
        # Read-only, no Create/Update/Delete/BatchCreatePartition -- dbt
        # never modifies this table, only queries it.
        Sid      = "ReadPaymentsEventsSource"
        Effect   = "Allow"
        Action   = ["glue:GetTable", "glue:GetPartitions"]
        Resource = local.glue_partition_table_arn
      },
      {
        Sid      = "RunAthenaQueries"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"]
        Resource = local.athena_workgroup_arn
      },
      {
        Sid      = "ReadWriteGold"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${var.bucket_arns["gold"]}/*"
      },
      {
        Sid      = "ListGold"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.bucket_arns["gold"]
      },
      {
        # Same reasoning as ReadPaymentsEventsSource above, one layer
        # down: Athena needs to actually read the underlying Parquet data
        # this role's queries scan, not just resolve Glue metadata -- the
        # same two-layer (catalog + data) permission split
        # cerberus-orchestration-transform's MSCK REPAIR fix already hit
        # earlier tonight.
        Sid      = "ReadSilverPaymentsSource"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${var.bucket_arns["silver"]}/payments/*"
      },
      {
        Sid      = "ListSilverPaymentsPrefixOnly"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.bucket_arns["silver"]
        Condition = {
          StringLike = { "s3:prefix" = ["payments/*"] }
        }
      },
      {
        Sid      = "WriteAthenaResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${var.athena_results_bucket_arn}/*"
      },
      {
        Sid      = "ListAthenaResults"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = var.athena_results_bucket_arn
      }
    ]
  })
}

# cerberus-orchestration-ecs-execution: shared by both task definitions
# above, distinct from either task's own role -- ECS's own two-role model
# (task role = what the app code inside the container can call; execution
# role = what the ECS agent uses to pull the image and deliver logs
# before the app code even starts). AWS-managed, not inline -- the same
# "runtime boilerplate" exception this module already makes for
# ingestion_lambda's AWSLambdaBasicExecutionRole.

resource "aws_iam_role" "orchestration_ecs_execution" {
  name = "cerberus-orchestration-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "orchestration_ecs_execution" {
  role       = aws_iam_role.orchestration_ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# cerberus-orchestration-state-machine: trust policy only. Its inline
# policy is attached in terraform/modules/step_functions (see that
# module's header) -- it needs ARNs (the ECS task definitions) that don't
# exist until after this module's own roles do.

resource "aws_iam_role" "orchestration_state_machine" {
  name = "cerberus-orchestration-state-machine"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "states.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

# --- Serving: read-only, gold/* -------------------------------------------

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
          # dbt-created marts (1.9) aren't Terraform-managed, so they're not
          # in glue_serving_table_arns -- same fct_*/dim_* wildcard scoping
          # cerberus-transform uses to own them.
          [local.glue_dbt_fct_table_arn, local.glue_dbt_dim_table_arn],
        )
      },
      {
        Sid      = "RunAthenaQueries"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"]
        Resource = local.athena_workgroup_arn
      },
      {
        # No s3:DeleteObject: serving only ever runs SELECTs, never
        # CTAS/DDL, so it has no reason to clear an existing location the
        # way cerberus-transform's dbt runs do.
        Sid      = "WriteAthenaResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${var.athena_results_bucket_arn}/*"
      },
      {
        Sid      = "ListAthenaResults"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = var.athena_results_bucket_arn
      }
    ]
  })
}
