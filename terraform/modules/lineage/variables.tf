variable "account_id" {
  description = "AWS account ID -- used to name the lineage bucket (cerberus-platform-lineage-<account-id>, the same pattern as the medallion buckets)."
  type        = string
}

variable "region" {
  description = "AWS region -- used to build the collector's invoke URL output."
  type        = string
  default     = "us-east-1"
}

variable "event_retention_days" {
  description = "OpenLineage event objects under events/ are expired after this many days. They are per-run operational records, not a data layer -- 90 days is plenty of history for 6.4d's rendering and any debugging, without unbounded growth."
  type        = number
  default     = 90
}

variable "collector_timeout_seconds" {
  description = "Collector Lambda timeout. One JSON parse plus one S3 PutObject -- 10s is generous."
  type        = number
  default     = 10
}

variable "throttle_rate_limit" {
  description = "Steady-state request/sec ceiling on the (unauthenticated) collector API stage. The pipeline emits a handful of events per run; this is an abuse ceiling, not a capacity limit."
  type        = number
  default     = 10
}

variable "throttle_burst_limit" {
  description = "Burst request ceiling on the collector API stage -- a Spark job can emit its START events for several datasets near-simultaneously, so the burst sits above the steady rate."
  type        = number
  default     = 20
}

variable "log_retention_days" {
  description = "Retention on the collector Lambda's and the API's access-log groups. 14 days matches the state machine / ECS runner / freshness probe log groups."
  type        = number
  default     = 14
}
