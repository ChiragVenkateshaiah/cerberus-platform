variable "silver_bucket_name" {
  description = "Silver bucket name (payments_events table location)."
  type        = string
}

variable "gold_bucket_name" {
  description = "Gold bucket name (payments_current table location)."
  type        = string
}
