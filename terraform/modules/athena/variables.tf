variable "account_id" {
  description = "AWS account ID, used to build the cerberus-platform-athena-results-<account-id> bucket name."
  type        = string
}

variable "results_expiration_days" {
  description = "Days before Athena query-result objects expire."
  type        = number
  default     = 7
}

variable "bytes_scanned_cutoff_bytes" {
  description = "Per-query bytes-scanned cutoff for the shared workgroup (dbt, serving, the collector) -- a cost guardrail. 1 GiB until 8.6, when dbt's incremental fct_transactions merge passed it at about 19M silver events (exercise-20261009T101830Z). At 10 GiB the worst single query costs about $0.05."
  type        = number
  default     = 10737418240 # 10 GiB
}

variable "dq_bytes_scanned_cutoff_bytes" {
  description = "Per-query bytes-scanned cutoff for the data-quality workgroup. Sized for the 10M step (bronze 4.36 GB) with headroom; not meant to stretch to 100M -- see the workgroup's comment."
  type        = number
  default     = 10737418240 # 10 GiB
}
