variable "account_id" {
  description = "AWS account ID, used to build Glue/Athena ARNs for the state machine's own inline policy."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "state_machine_role_arn" {
  description = "cerberus-orchestration-state-machine IAM role ARN (iam module) -- trust policy only, this module attaches the inline policy (see main.tf's header for why)."
  type        = string
}

variable "state_machine_role_name" {
  description = "cerberus-orchestration-state-machine IAM role name (iam module) -- needed alongside the ARN above since aws_iam_role_policy attaches by name."
  type        = string
}

variable "ingestion_lambda_arn" {
  description = "The ingestion Lambda's ARN (lambda_ingestion module) -- the InvokeIngestion state's target."
  type        = string
}

variable "ecs_cluster_arn" {
  description = "The orchestration ECS cluster's ARN (orchestration_runner module)."
  type        = string
}

variable "transform_task_definition_arn" {
  description = "The transform task definition's ARN (orchestration_runner module)."
  type        = string
}

variable "dbt_task_definition_arn" {
  description = "The dbt task definition's ARN (orchestration_runner module)."
  type        = string
}

variable "transform_task_role_arn" {
  description = "cerberus-orchestration-transform IAM role ARN (iam module) -- needed for the state machine role's iam:PassRole grant."
  type        = string
}

variable "dbt_task_role_arn" {
  description = "cerberus-orchestration-dbt IAM role ARN (iam module) -- needed for the state machine role's iam:PassRole grant."
  type        = string
}

variable "task_execution_role_arn" {
  description = "cerberus-orchestration-ecs-execution IAM role ARN (iam module) -- needed for the state machine role's iam:PassRole grant."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs (vpc module) -- the ECS RunTask states' NetworkConfiguration."
  type        = list(string)
}

variable "security_group_id" {
  description = "The runner tasks' security group ID (orchestration_runner module)."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup name (athena module) -- the RunServingQuery state's WorkGroup, and the state machine role's Athena grant."
  type        = string
}

variable "athena_database_name" {
  description = "Glue database name (glue_catalog module) -- the RunServingQuery state's QueryExecutionContext.Database."
  type        = string
}

variable "athena_results_bucket_arn" {
  description = "Athena query-results bucket ARN (athena module) -- the state machine role's results read/write grant."
  type        = string
}

variable "gold_bucket_arn" {
  description = "Gold bucket ARN (s3_medallion module) -- the state machine role's read grant for the serving query."
  type        = string
}

variable "schedule_expression" {
  description = "EventBridge Scheduler cron/rate expression for the daily orchestrated run -- moved here from lambda_ingestion (4.3), same default it used."
  type        = string
  default     = "cron(0 0 * * ? *)" # daily at 00:00 UTC
}

variable "schedule_timezone" {
  description = "Schedule timezone -- fixed to UTC per ADR 0005 (events are partitioned by UTC event day), same as lambda_ingestion's schedule before this moved here."
  type        = string
  default     = "UTC"
}

variable "pipeline_active" {
  description = <<-EOT
    Whether the orchestrated pipeline is expected to be live right now.
    Defaults false: the daily schedule below is created DISABLED, because
    the pipeline's RunTransform step submits a Spark job to the
    envs/dev-compute EKS cluster, which is torn down between compute
    exercises by design (ADR 0007/0011). An ENABLED schedule while
    dev-compute is down fires a run that structurally cannot succeed --
    it fails at RunTransform every day, burning Fargate task starts and
    accruing failed executions. Flip to true as the first step of a
    compute exercise (before applying dev-compute), back to false at
    teardown. See docs/adr/0011 (amended 2026-09-01) and dev-compute's
    module header for the runbook.
  EOT
  type        = bool
  default     = false
}
