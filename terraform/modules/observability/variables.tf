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

# --- 6.2: alarms + slow-job alerting ---------------------------------

variable "pipeline_active" {
  description = <<-EOT
    Threaded from envs/dev-standing -- the same switch that ENABLEs the
    daily schedule (ADR 0011, amended 2026-09-01). false (default): the
    pipeline-health and data-freshness alarms are NOT created, because the
    whole pipeline is dormant by design while dev-compute (EKS) is torn
    down and every signal is legitimately stale -- alarms on it then would
    page daily for a non-problem. true: those alarms exist and notify. The
    two freshness-probe self-health alarms are created either way (the
    probe runs hourly regardless).
  EOT
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Address subscribed to the cerberus-pipeline-alerts SNS topic. Terraform creates the subscription 'pending confirmation' -- the recipient must click the link AWS emails once, after the first apply that creates it."
  type        = string
}

variable "slow_execution_threshold_ms" {
  description = "cerberus-pipeline-execution-slow fires when a state-machine ExecutionTime (Maximum) exceeds this. Default 45min -- generous headroom over a real end-to-end run (the EKS spin-up is a separate manual step, not on this clock); tune down once there's a run-duration baseline."
  type        = number
  default     = 2700000
}

variable "pipeline_run_freshness_threshold_seconds" {
  description = "cerberus-freshness-pipeline-run fires when FreshnessSeconds{PipelineRun} -- age of the last SUCCEEDED execution -- exceeds this. Default 36h: one missed daily run plus slack."
  type        = number
  default     = 129600
}

variable "gold_data_freshness_threshold_seconds" {
  description = "cerberus-freshness-gold-data fires when FreshnessSeconds{GoldData} exceeds this. Default 36h -- a healthy daily run refreshes the gold bucket."
  type        = number
  default     = 129600
}
