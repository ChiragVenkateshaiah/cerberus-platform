variable "account_id" {
  description = "AWS account ID -- used to name the site bucket (cerberus-platform-console-<account-id>, the same pattern as the medallion and lineage buckets)."
  type        = string
}

variable "region" {
  description = "AWS region -- used to build the Cognito hosted-UI host and the HTTP API origin host."
  type        = string
  default     = "us-east-1"
}

variable "console_cli_role_arn" {
  description = "ARN of cerberus-console-cli (from console_roles) -- the execution role of the command Lambda."
  type        = string
}

variable "console_cli_role_name" {
  description = "Name of cerberus-console-cli -- the role that receives the separate cerberus-console-cli-logs inline policy."
  type        = string
}

variable "state_machine_arn" {
  description = "ARN of the pipeline state machine -- passed to the command Lambda as CERBERUS_STATE_MACHINE_ARN, for the read-only run listings."
  type        = string
}

variable "cognito_domain_prefix" {
  description = "Prefix of the Cognito hosted-UI domain (<prefix>.auth.<region>.amazoncognito.com). A plain string, not a resource reference, so the CSP header can name it without a dependency cycle. Prefixes are global: change it if apply reports the prefix as taken."
  type        = string
  default     = "cerberus-console"
}

variable "throttle_rate_limit" {
  description = "Steady-state request/sec ceiling on the console API stage (ADR 0024 amendment 2026-11-02). With no reserved concurrency this throttle, plus invite-only sign-in, is the cost bound."
  type        = number
  default     = 1
}

variable "throttle_burst_limit" {
  description = "Burst request ceiling on the console API stage."
  type        = number
  default     = 3
}

variable "command_reserved_concurrency" {
  description = "Reserved concurrency for the command Lambda. -1 leaves it unreserved. Set 2 only when the account's concurrent-executions limit is at least 102 (AWS requires the unreserved pool to stay at 100 or more); the account limit was 10 on 2026-11-02."
  type        = number
  default     = -1
}

variable "lambda_timeout_seconds" {
  description = "Command Lambda timeout (ADR 0024 rule 8: 25 s)."
  type        = number
  default     = 25
}

variable "lambda_memory_mb" {
  description = "Command Lambda memory."
  type        = number
  default     = 256
}

variable "token_validity_minutes" {
  description = "Access, ID and refresh token lifetime for the app client. 60 minutes is the Cognito minimum for the refresh token (ADR 0024)."
  type        = number
  default     = 60
}

variable "log_retention_days" {
  description = "Retention on the command Lambda's log group. 14 days matches the other Lambda log groups."
  type        = number
  default     = 14
}

variable "access_log_retention_days" {
  description = "Retention on the API access-log group. 30 days covers the audit window for a month of invites (ADR 0024 rule 9)."
  type        = number
  default     = 30
}
