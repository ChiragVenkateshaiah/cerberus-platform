# 6.1 (Phase 6 -- Observability & data quality). Two deliverables, both
# always-on / no-idle-cost, which is why this module is instantiated from
# envs/dev-standing alongside the orchestration layer rather than from
# envs/dev-compute -- the same placement reasoning ADR 0011 used:
#
#   1. A single CloudWatch dashboard over metrics AWS already publishes for
#      the pipeline -- Step Functions execution outcomes/duration, the
#      ingestion Lambda, the Athena serving query, and per-integration
#      timing. One dashboard stays within CloudWatch's 3-dashboard free
#      tier. No new emitters for this part.
#
#   2. A "freshness probe" Lambda (observability/freshness_probe/handler.py)
#      on its own hourly EventBridge Scheduler, publishing
#      Cerberus/Pipeline -> FreshnessSeconds{Signal} custom metrics.
#      CloudWatch has no native "time since last write" metric and dashboard
#      metric math has no now(), so a "seconds stale" number needs an
#      external observer on its own clock -- see the handler's docstring.
#      6.2 hangs its data-freshness alarms off these metrics.

locals {
  dashboard_name = "cerberus-platform-pipeline"
  probe_name     = "cerberus-freshness-probe"
}

# --- 1. Dashboard ------------------------------------------------------

resource "aws_cloudwatch_dashboard" "pipeline" {
  dashboard_name = local.dashboard_name

  dashboard_body = templatefile("${path.module}/dashboard.json.tftpl", {
    region                = var.region
    state_machine_arn     = var.state_machine_arn
    ingestion_lambda_name = var.ingestion_lambda_name
    athena_workgroup      = var.athena_workgroup_name
    probe_name            = local.probe_name
  })
}

# --- 2. Freshness probe Lambda ---------------------------------------
# Single committed handler.py, no dependency layer -- the probe imports
# only boto3, which the python3.12 runtime already ships. So a plain
# archive_file over one file, no null_resource/pip step (unlike
# lambda_ingestion, which needs Faker packaged).

data "archive_file" "probe" {
  type        = "zip"
  output_path = "${path.module}/build/freshness_probe.zip"

  source {
    content  = file("${path.module}/../../../observability/freshness_probe/handler.py")
    filename = "handler.py"
  }
}

# Self-contained execution role -- not terraform/modules/iam. Same
# reasoning the step_functions module gives for keeping its scheduler role
# local: this policy is 1:1 with this one Lambda and is coupled to the
# state machine ARN (states:ListExecutions is resource-scoped to it), which
# this module already receives. Threading a new role plus that ARN through
# the central iam module buys nothing.
resource "aws_iam_role" "probe" {
  name = local.probe_name

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

# CloudWatch Logs boilerplate -- the same AWS-managed-policy exception
# terraform/modules/iam already makes for the ingestion Lambda.
resource "aws_iam_role_policy_attachment" "probe_logs" {
  role       = aws_iam_role.probe.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "probe" {
  name = "${local.probe_name}-policy"
  role = aws_iam_role.probe.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadPipelineExecutions"
        Effect   = "Allow"
        Action   = "states:ListExecutions"
        Resource = var.state_machine_arn
      },
      {
        Sid    = "ListBronzeAndGold"
        Effect = "Allow"
        Action = "s3:ListBucket"
        Resource = [
          var.bronze_bucket_arn,
          var.gold_bucket_arn,
        ]
      },
      {
        # PutMetricData has no resource-level scoping -- AWS only supports
        # constraining it by namespace via a condition key, which is what
        # this does (the same "*"-with-condition shape the Well-Architected
        # reviews already note for Step Functions' logs/X-Ray grants).
        Sid      = "PublishFreshnessMetrics"
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"
        Condition = {
          StringEquals = { "cloudwatch:namespace" = "Cerberus/Pipeline" }
        }
      }
    ]
  })
}

resource "aws_lambda_function" "probe" {
  function_name = local.probe_name
  role          = aws_iam_role.probe.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = var.probe_timeout_seconds
  memory_size   = 128

  filename         = data.archive_file.probe.output_path
  source_code_hash = data.archive_file.probe.output_base64sha256

  environment {
    variables = {
      STATE_MACHINE_ARN = var.state_machine_arn
      BRONZE_BUCKET     = var.bronze_bucket_name
      GOLD_BUCKET       = var.gold_bucket_name
    }
  }
}

# Explicit log group so its retention is managed (14 days, matching the
# state machine's and the ECS runner's log groups) rather than left to
# Lambda's implicit never-expire default.
resource "aws_cloudwatch_log_group" "probe" {
  name              = "/aws/lambda/${local.probe_name}"
  retention_in_days = 14
}

# --- 3. Hourly trigger ----------------------------------------------
# Self-contained scheduler role, mirroring step_functions' own scheduler
# role exactly (the pattern 4.3 established). EventBridge Scheduler invokes
# Lambda by assuming this role and calling lambda:InvokeFunction -- no
# resource-based aws_lambda_permission is needed (that's an EventBridge
# *Rules* requirement, not a Scheduler one).

resource "aws_iam_role" "scheduler" {
  name = "${local.probe_name}-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "scheduler.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "invoke-freshness-probe"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.probe.arn
      }
    ]
  })
}

resource "aws_scheduler_schedule" "probe" {
  name       = "${local.probe_name}-hourly"
  group_name = "default"

  schedule_expression          = var.probe_schedule_expression
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.probe.arn
    role_arn = aws_iam_role.scheduler.arn

    # The probe is a pure read + PutMetricData, fully idempotent -- a
    # retried invocation just refreshes the same datapoints, so unlike the
    # ingestion path (ADR 0005) there's no reason to force attempts to 0.
    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}
