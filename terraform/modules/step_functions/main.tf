# 4.2 -- the orchestrated ingest -> transform -> dbt -> serve state machine
# (ADR 0009). InvokeIngestion re-invokes the existing 2.1 Lambda directly;
# RunTransform/RunDbt drive the orchestration_runner module's two Fargate
# tasks via the native ecs:runTask.sync2 integration; RunServingQuery runs
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
        # AWS's own documented requirement for the ecs:runTask.sync2
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
      }
    ]
  })
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

  depends_on = [aws_iam_role_policy.state_machine]
}
