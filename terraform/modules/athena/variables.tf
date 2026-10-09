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
  description = "Per-query bytes-scanned cutoff for the workgroup -- a cost guardrail, not a real constraint at this data volume."
  type        = number
  default     = 1073741824 # 1 GiB
}

variable "dq_bytes_scanned_cutoff_bytes" {
  description = "Per-query bytes-scanned cutoff for the data-quality workgroup. Sized for the 10M step (bronze 4.36 GB) with headroom; not meant to stretch to 100M -- see the workgroup's comment."
  type        = number
  default     = 10737418240 # 10 GiB
}
