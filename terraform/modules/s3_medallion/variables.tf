variable "account_id" {
  description = "AWS account ID, used to build the cerberus-platform-<layer>-<account-id> bucket names."
  type        = string
}

variable "bronze_ia_transition_days" {
  description = "Days before bronze objects transition to S3 Standard-IA (ADR 0002)."
  type        = number
  default     = 30
}
