# Two read-only roles for the demo console (ADR 0024, 9.2). Standing and
# $0: IAM roles and inline policies carry no charge, and sts:AssumeRole is
# free.
#
# cerberus-grafana-read is what the local Grafana assumes (`make grafana-up`)
# in place of the mounted AWS profile. Its policy is exactly the AMP query and
# CloudWatch read set the story dashboards were proven with in 7.7/7.8 (the
# in-cluster `cerberus-grafana` role, removed in ADR 0024 step 11): AMP
# query on the workspace plus read-only CloudWatch. Sessions can last up to
# 12 h.
#
# cerberus-console-cli is the role every console command runs as. It reads
# Step Functions, runs one fixed Athena query in the console workgroup, and
# reads gold table metadata only (never data files). Its only write is the
# console/ results prefix. It has no glue:UpdateTable and no s3:PutObject
# outside that prefix.
#
# Trust is set at creation. CI has no iam:UpdateAssumeRolePolicy, so a later
# trust change needs a local cerberus-admin apply. Inline policies, as in
# the iam module: each is scoped 1:1 to one role.

locals {
  state_machine_execution_arn = "arn:aws:states:${var.region}:${var.account_id}:execution:${var.state_machine_name}:*"

  glue_database_arn = "arn:aws:glue:${var.region}:${var.account_id}:database/${var.glue_database_name}"
  glue_table_arns   = [for t in var.gold_table_names : "arn:aws:glue:${var.region}:${var.account_id}:table/${var.glue_database_name}/${t}"]
}

# --- cerberus-grafana-read: local Grafana, AMP + CloudWatch read --------

resource "aws_iam_role" "grafana_read" {
  name                 = "cerberus-grafana-read"
  max_session_duration = 43200

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

  tags = {
    Phase     = "9"
    Component = "console"
  }
}

resource "aws_iam_role_policy" "grafana_read" {
  name = "cerberus-grafana-read-policy"
  role = aws_iam_role.grafana_read.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "QueryWorkspace"
        Effect = "Allow"
        Action = [
          "aps:QueryMetrics", "aps:GetSeries", "aps:GetLabels", "aps:GetMetricMetadata",
        ]
        Resource = var.amp_workspace_arn
      },
      {
        # Same set the removed in-cluster role had. None of these
        # support resource-level scoping. ec2:DescribeRegions populates the
        # data source's region picker.
        Sid    = "ReadCloudWatchMetrics"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmsForMetric", "cloudwatch:DescribeAlarmHistory",
          "ec2:DescribeRegions",
        ]
        Resource = "*"
      }
    ]
  })
}

# --- cerberus-console-cli: console commands --------------------------

resource "aws_iam_role" "console_cli" {
  name = "cerberus-console-cli"

  # Lambda (the console API, 9.2 step 7) and cerberus-admin (local runs of
  # the command set, 9.3).
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      },
      {
        Effect    = "Allow"
        Principal = { AWS = var.trusted_principal_arn }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Phase     = "9"
    Component = "console"
  }
}

resource "aws_iam_role_policy" "console_cli" {
  name = "cerberus-console-cli-policy"
  role = aws_iam_role.console_cli.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadStateMachine"
        Effect   = "Allow"
        Action   = ["states:DescribeStateMachine", "states:ListExecutions"]
        Resource = var.state_machine_arn
      },
      {
        Sid      = "ReadExecutions"
        Effect   = "Allow"
        Action   = ["states:DescribeExecution", "states:GetExecutionHistory"]
        Resource = local.state_machine_execution_arn
      },
      {
        Sid    = "RunConsoleQuery"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults",
          "athena:StopQueryExecution", "athena:GetWorkGroup",
        ]
        Resource = "arn:aws:athena:${var.region}:${var.account_id}:workgroup/${var.athena_workgroup_name}"
      },
      {
        # Exactly the gold tables the fixed query names. The catalog ARN is
        # required alongside the database and tables.
        Sid    = "ReadGoldCatalog"
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetTable"]
        Resource = concat(
          ["arn:aws:glue:${var.region}:${var.account_id}:catalog", local.glue_database_arn],
          local.glue_table_arns,
        )
      },
      {
        # Iceberg metadata trees only. Gold data files stay unreadable.
        Sid      = "ReadGoldMetadata"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = [for t in var.gold_table_names : "${var.gold_bucket_arn}/${var.glue_database_name}/${t}/*/metadata/*"]
      },
      {
        Sid      = "WriteConsoleResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
        Resource = "${var.athena_results_bucket_arn}/${var.athena_results_prefix}*"
      },
      {
        Sid      = "ListConsoleResults"
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation"]
        Resource = var.athena_results_bucket_arn
      },
      {
        Sid      = "ListConsoleResultsPrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = var.athena_results_bucket_arn
        Condition = {
          StringLike = { "s3:prefix" = ["${var.athena_results_prefix}*"] }
        }
      }
    ]
  })
}
