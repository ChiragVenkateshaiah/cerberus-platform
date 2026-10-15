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
  description = "Per-query bytes-scanned cutoff for the shared workgroup (dbt, serving, the collector) -- a cost guardrail. 1 GiB until 8.6, when dbt's incremental fct_transactions merge passed it at about 19M silver events (exercise-20261009T101830Z). Raised to 10 GiB then, and to 25 GiB for 8.9: at 37M silver events the merge scanned 3.18 GiB (exercise-20261012T133620Z), about 12 GiB projected at the ~137M of the 100M step. At 25 GiB the worst single query costs about $0.13. The time spread (docs/plan.md, Planned later work) is what makes the merge prune instead."
  type        = number
  default     = 26843545600 # 25 GiB
}

variable "dq_bytes_scanned_cutoff_bytes" {
  description = "Per-query bytes-scanned cutoff for the data-quality workgroup. Sized for the 10M step (bronze 4.36 GB) with headroom; not meant to stretch to 100M -- see the workgroup's comment. Raised to 80 GiB on 2026-10-15 for one `data_quality.py --full` audit before milestone 8 (#103; each whole-bronze query reads all 59.3 GB of bronze at 137M events) and put back after it (docs/scale-metrics.md, Milestone audit)."
  type        = number
  default     = 10737418240 # 10 GiB
}
