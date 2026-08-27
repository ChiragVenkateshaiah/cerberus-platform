variable "region" {
  description = "AWS region -- used in the dashboard's per-widget region field."
  type        = string
  default     = "us-east-1"
}

variable "state_machine_arn" {
  description = "Orchestration state machine ARN (step_functions module) -- the dashboard's Step Functions widgets and the probe's states:ListExecutions grant."
  type        = string
}

variable "ingestion_lambda_name" {
  description = "Ingestion Lambda function name (lambda_ingestion module) -- the dashboard's AWS/Lambda widget dimension."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup name (athena module) -- the dashboard's AWS/Athena serving-query widget dimension."
  type        = string
}

variable "bronze_bucket_name" {
  description = "Bronze bucket name (s3_medallion module) -- passed to the freshness probe as BRONZE_BUCKET."
  type        = string
}

variable "bronze_bucket_arn" {
  description = "Bronze bucket ARN (s3_medallion module) -- the probe role's s3:ListBucket grant."
  type        = string
}

variable "gold_bucket_name" {
  description = "Gold bucket name (s3_medallion module) -- passed to the freshness probe as GOLD_BUCKET."
  type        = string
}

variable "gold_bucket_arn" {
  description = "Gold bucket ARN (s3_medallion module) -- the probe role's s3:ListBucket grant."
  type        = string
}

variable "probe_schedule_expression" {
  description = "EventBridge Scheduler rate/cron expression for the freshness probe. Hourly by default -- fresh enough for a once-daily pipeline without a meaningful metric cost."
  type        = string
  default     = "rate(1 hour)"
}

variable "probe_timeout_seconds" {
  description = "Freshness probe Lambda timeout. Two ListBucket paginations plus one ListExecutions and one PutMetricData -- 30s is generous."
  type        = number
  default     = 30
}
