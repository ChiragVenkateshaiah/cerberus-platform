variable "account_id" {
  description = "AWS account ID, used to build the Step Functions execution ARN pattern."
  type        = string
}

variable "region" {
  description = "AWS region, used to build the Step Functions execution ARN pattern."
  type        = string
  default     = "us-east-1"
}

variable "trusted_principal_arn" {
  description = "The IAM principal (cerberus-admin) allowed to assume both roles by hand, as in the iam module."
  type        = string
}

variable "amp_workspace_arn" {
  description = "ARN of the AMP workspace that cerberus-grafana-read may query."
  type        = string
}

variable "state_machine_arn" {
  description = "ARN of the orchestration state machine that cerberus-console-cli may describe and list."
  type        = string
}

variable "state_machine_name" {
  description = "Name of the orchestration state machine, used to scope the execution ARN pattern."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Name of the console Athena workgroup that cerberus-console-cli may run queries in."
  type        = string
}

variable "athena_results_bucket_arn" {
  description = "ARN of the Athena query-results bucket."
  type        = string
}

variable "athena_results_prefix" {
  description = "Key prefix in the results bucket that cerberus-console-cli may write, with the trailing slash (for example console/)."
  type        = string
}

variable "gold_bucket_arn" {
  description = "ARN of the gold bucket, whose Iceberg metadata cerberus-console-cli may read."
  type        = string
}

variable "glue_database_name" {
  description = "Name of the Glue database that holds the gold tables."
  type        = string
}

variable "gold_table_names" {
  description = "Gold tables the console's fixed query reads. Must match GOLD_TABLES in console/cerberus_console/config.py."
  type        = list(string)
  default     = ["fct_transactions", "dim_customers", "dim_merchants"]
}
