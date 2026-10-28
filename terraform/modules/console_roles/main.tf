# Two read-only roles for the demo console (ADR 0024, 9.2). Standing and
# $0: IAM roles and inline policies carry no charge, and sts:AssumeRole is
# free.
#
# cerberus-grafana-read is what the local Grafana assumes (`make grafana-up`)
# in place of the mounted AWS profile. Its policy is exactly the in-cluster
# cerberus-grafana set (eks_observability), so the story dashboards already
# proven in 7.7/7.8 need nothing new: AMP query on the workspace plus
# read-only CloudWatch. Sessions can last up to 12 h.
#
# cerberus-console-cli is the role every console command runs as. For now it
# reads Step Functions only. The Athena, Glue and gold-read statements (and
# the workgroup and result prefix they need) arrive with the command set in
# 9.3, together with the fixed queries they serve, because the bytes scanned
# and the table set are not known yet. It has no write action anywhere: no
# glue:UpdateTable, no s3:PutObject.
#
# Trust is set at creation. CI has no iam:UpdateAssumeRolePolicy, so a later
# trust change needs a local cerberus-admin apply. Inline policies, as in
# the iam module: each is scoped 1:1 to one role.

locals {
  state_machine_execution_arn = "arn:aws:states:${var.region}:${var.account_id}:execution:${var.state_machine_name}:*"
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
        # Same set as the in-cluster cerberus-grafana role. None of these
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

# --- cerberus-console-cli: console commands, Step Functions read only ----

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
      }
    ]
  })
}
