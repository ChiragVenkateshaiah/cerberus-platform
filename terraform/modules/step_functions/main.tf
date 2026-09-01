# 4.2 -- the orchestrated ingest -> transform -> dbt -> serve state machine
# (ADR 0009). InvokeIngestion re-invokes the existing 2.1 Lambda directly;
# RunTransform/RunDbt drive the orchestration_runner module's two Fargate
# tasks via the native ecs:runTask.sync integration; RunServingQuery runs
# serving/queries/demo_query.sql (1.10) via the native
# athena:startQueryExecution.sync integration -- no container needed for
# that step, Step Functions talks to Athena directly.
#
# This module also owns the state-machine execution role's *inline
# policy* -- not terraform/modules/iam, where every other role in this
# project lives. Deliberate, narrow exception: that policy needs the ECS
# task-definition ARNs orchestration_runner creates, and orchestration_runner
# itself needs iam's task-role ARNs -- attaching the policy here, to a
# role iam still creates the trust policy for (role_arns["orchestration_state_machine"]),
# is what avoids the resulting module dependency cycle.
#
# 4.3 adds two things beyond 4.2's baseline: execution-level visibility
# (CloudWatch Logs + X-Ray on the state machine itself) and the
# EventBridge Scheduler trigger, moved here from lambda_ingestion (see the
# bottom of this file) now that there's a state machine for it to start
# instead of invoking the Lambda directly -- the item ADR 0009 explicitly
# left open for this subtask. The scheduler's own execution role is
# self-contained in this module, not centralized in terraform/modules/iam
# -- mirroring the exact pattern lambda_ingestion's own scheduler role
# already used before this move.

locals {
  glue_catalog_arn  = "arn:aws:glue:${var.region}:${var.account_id}:catalog"
  glue_database_arn = "arn:aws:glue:${var.region}:${var.account_id}:database/${var.athena_database_name}"
  # dbt's own fct_*/dim_* wildcard scoping, same pattern the iam module
  # already uses for cerberus-transform/cerberus-serving -- these tables
  # aren't Terraform-managed, so no exact table name to reference.
  glue_dbt_fct_table_arn = "arn:aws:glue:${var.region}:${var.account_id}:table/${var.athena_database_name}/fct_*"
  glue_dbt_dim_table_arn = "arn:aws:glue:${var.region}:${var.account_id}:table/${var.athena_database_name}/dim_*"
  athena_workgroup_arn   = "arn:aws:athena:${var.region}:${var.account_id}:workgroup/${var.athena_workgroup_name}"

  demo_query = file("${path.module}/../../../serving/queries/demo_query.sql")
}

resource "aws_iam_role_policy" "state_machine" {
  name = "cerberus-orchestration-state-machine-policy"
  role = var.state_machine_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeIngestion"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = var.ingestion_lambda_arn
      },
      {
        Sid    = "RunOrchestrationTasks"
        Effect = "Allow"
        Action = ["ecs:RunTask", "ecs:StopTask", "ecs:DescribeTasks"]
        Resource = [
          var.transform_task_definition_arn,
          var.dbt_task_definition_arn,
        ]
      },
      {
        Sid    = "PassOrchestrationTaskRoles"
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = [
          var.transform_task_role_arn,
          var.dbt_task_role_arn,
          var.task_execution_role_arn,
        ]
      },
      {
        # AWS's own documented requirement for the ecs:runTask.sync
        # integration: Step Functions creates/manages a rule named
        # "StepFunctionsGetEventsForECSTaskRule" to hear the task's
        # completion event -- this just grants the state machine's role
        # permission to let it, not a broader EventBridge grant.
        Sid      = "ManageEcsSyncEventRule"
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = "arn:aws:events:${var.region}:${var.account_id}:rule/StepFunctionsGetEventsForECSTaskRule"
      },
      {
        Sid      = "RunServingQuery"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"]
        Resource = local.athena_workgroup_arn
      },
      {
        Sid    = "ReadServingCatalog"
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
        Resource = [
          local.glue_catalog_arn,
          local.glue_database_arn,
          local.glue_dbt_fct_table_arn,
          local.glue_dbt_dim_table_arn,
        ]
      },
      {
        Sid      = "ReadGold"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${var.gold_bucket_arn}/*"
      },
      {
        Sid      = "ListGold"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.gold_bucket_arn
      },
      {
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
      },
      {
        # AWS's own documented requirement for Step Functions' CloudWatch
        # Logs execution logging (4.3) -- none of these actions support
        # resource-level scoping narrower than "*" (confirmed against
        # AWS's own example policy for this feature), unlike everything
        # else in this policy.
        Sid    = "DeliverExecutionLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups",
        ]
        Resource = "*"
      },
      {
        # Same "*"-only constraint as above, AWS's own documented
        # requirement for X-Ray tracing (4.3).
        Sid    = "WriteTraceSegments"
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
        ]
        Resource = "*"
      }
    ]
  })
}

# 4.3: execution-level visibility. /aws/vendedlogs/states/ is AWS's own
# naming convention for Step Functions log groups -- using it is what
# lets AWS's default resource policy for log delivery apply without
# hand-writing a custom one. 14-day retention matches orchestration_runner's
# two ECS log groups.
resource "aws_cloudwatch_log_group" "state_machine" {
  name              = "/aws/vendedlogs/states/cerberus-platform-orchestration"
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "orchestration" {
  name     = "cerberus-platform-orchestration"
  role_arn = var.state_machine_role_arn
  # Standard, not Express -- ADR 0009's own reasoning: this is a
  # once-daily, few-step pipeline, not a high-volume workload. Standard's
  # exactly-once semantics and up-to-one-year execution history are a real
  # asset for a portfolio project a reviewer might look at months later.
  type = "STANDARD"

  definition = templatefile("${path.module}/../../../orchestration/state_machine.asl.json.tftpl", {
    ingestion_lambda_arn          = var.ingestion_lambda_arn
    ecs_cluster_arn               = var.ecs_cluster_arn
    transform_task_definition_arn = var.transform_task_definition_arn
    dbt_task_definition_arn       = var.dbt_task_definition_arn
    subnet_ids_json               = jsonencode(var.private_subnet_ids)
    security_group_id             = var.security_group_id
    athena_workgroup              = var.athena_workgroup_name
    athena_database               = var.athena_database_name
    demo_query_json               = jsonencode(local.demo_query)
  })

  # 4.3: ALL + execution data -- every state transition's full input/output
  # lands in CloudWatch Logs, not just errors. Worth the (small, at this
  # execution volume) extra log cost for a portfolio project where a
  # reviewer being able to see exactly what a run did matters more than
  # trimming log verbosity.
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.state_machine.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  # 4.3: X-Ray -- one trace per execution spanning the Lambda invoke, both
  # ECS tasks, and the Athena query, so a slow run's actual bottleneck
  # (not just which state failed) is visible without cross-referencing
  # four different services' own logs by hand.
  tracing_configuration {
    enabled = true
  }

  depends_on = [aws_iam_role_policy.state_machine]
}

# --- EventBridge Scheduler trigger (4.3) ------------------------------
# Moved here from lambda_ingestion (see terraform/envs/dev/main.tf's
# `moved` blocks) now that there's a state machine to start instead of
# invoking the Lambda directly -- retargeting this was explicitly left to
# 4.3 by ADR 0009. Same daily-UTC shape as before; only the target and
# this role's permission changed.

resource "aws_iam_role" "scheduler" {
  # Name deliberately unchanged from before this moved here (was
  # "cerberus-ingest-payments-scheduler" in lambda_ingestion) -- IAM role
  # names are immutable (ForceNew), so renaming it here would force a
  # replace despite the `moved` block in envs/dev/main.tf, defeating the
  # point of using one. Only the inline policy below actually changes.
  name = "cerberus-ingest-payments-scheduler"

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

resource "aws_iam_role_policy" "scheduler_start_execution" {
  name = "start-orchestration-execution"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = aws_sfn_state_machine.orchestration.arn
      }
    ]
  })
}

resource "aws_scheduler_schedule" "daily" {
  # Name also deliberately unchanged, same reasoning as the role above --
  # aws_scheduler_schedule's name is ForceNew too.
  name       = "cerberus-ingest-payments-daily"
  group_name = "default"

  # ADR 0011 (amended 2026-09-01): DISABLED unless a compute exercise is
  # active. The whole pipeline -- ingestion included, since 4.3 folded the
  # only schedule into InvokeIngestion's parent -- is dormant by design
  # while envs/dev-compute (EKS) is torn down, which is the normal state.
  # An ENABLED schedule then just fails RunTransform daily. `state` is an
  # in-place update, no destroy/recreate.
  state = var.pipeline_active ? "ENABLED" : "DISABLED"

  # UTC, fixed explicitly -- same reasoning as the schedule this replaced
  # (ADR 0005): the pipeline's data is partitioned by UTC event day.
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    # Universal target: starts an execution of the state machine rather
    # than invoking a specific service API's dedicated integration.
    # Service name is "sfn", not "states" -- confirmed live 2026-08-20
    # against AWS's own EventBridge Scheduler docs after "states" failed
    # with "The api startExecution is not valid for the service
    # aws-sdk:states."
    arn      = "arn:aws:scheduler:::aws-sdk:sfn:startExecution"
    role_arn = aws_iam_role.scheduler.arn

    input = jsonencode({
      StateMachineArn = aws_sfn_state_machine.orchestration.arn
    })

    # Stays 0, carrying ADR 0005's exact reasoning forward one level: a
    # scheduler retry here means starting a *new execution*, which
    # re-invokes the ingestion Lambda from scratch and regenerates a
    # different, unseeded dataset -- same duplicate-data risk ADR 0005
    # eliminated at the direct-Lambda-invoke layer, just one hop removed.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
