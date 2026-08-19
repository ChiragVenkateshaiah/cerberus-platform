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
