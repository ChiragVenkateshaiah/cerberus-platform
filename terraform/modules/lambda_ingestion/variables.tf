variable "bronze_bucket_name" {
  description = "Bronze bucket name, passed to the Lambda as BRONZE_BUCKET."
  type        = string
}

variable "execution_role_arn" {
  description = "The Lambda's execution role ARN -- ingestion_lambda from the iam module (2.3), scoped to s3:PutObject on bronze/payments/* only, plus CloudWatch Logs."
  type        = string
}

variable "retire_on_or_after" {
  description = "Date (YYYY-MM-DD, UTC) on/after which the Lambda no-ops instead of generating. Originally 2026-08-17 (ADR 0005, kept in sync with the now-retired ingestion/scripts/run_payments_scheduled.sh's own cap -- that systemd path was fully decommissioned at 2.5, so this variable is the only place the cap lives now). Bumped to 2026-10-15 for 7.1's scaled-up workload exercise -- same data-volume-control rationale as before, not cost, just a later date."
  type        = string
  default     = "2026-10-15"
}

variable "transaction_count" {
  description = "Transactions generated per invocation, passed to the Lambda as TRANSACTION_COUNT. Bumped 200 -> 2000 for 7.1 (scaled-up synthetic payments workload)."
  type        = number
  default     = 2000
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout."
  type        = number
  default     = 60
}

variable "lambda_memory_mb" {
  description = "Lambda memory allocation."
  type        = number
  default     = 256
}
