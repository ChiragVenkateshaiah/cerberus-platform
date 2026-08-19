variable "bronze_bucket_name" {
  description = "Bronze bucket name, passed to the Lambda as BRONZE_BUCKET."
  type        = string
}

variable "execution_role_arn" {
  description = "The Lambda's execution role ARN -- ingestion_lambda from the iam module (2.3), scoped to s3:PutObject on bronze/payments/* only, plus CloudWatch Logs."
  type        = string
}

variable "retire_on_or_after" {
  description = "Date (YYYY-MM-DD, UTC) on/after which the Lambda no-ops instead of generating. Same window ingestion/scripts/run_payments_scheduled.sh already started -- kept in sync with that script's RETIRE_ON_OR_AFTER by hand (decided 2026-08-11: keep the cap for data-volume control, not cost -- ADR 0005)."
  type        = string
  default     = "2026-08-17"
}

variable "transaction_count" {
  description = "Transactions generated per invocation, passed to the Lambda as TRANSACTION_COUNT."
  type        = number
  default     = 200
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
