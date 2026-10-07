variable "silver_bucket_name" {
  description = "Silver bucket name (payments_events table location)."
  type        = string
}

variable "gold_bucket_name" {
  description = "Gold bucket name (payments_current table location)."
  type        = string
}

variable "bronze_bucket_name" {
  description = "Bronze bucket name (bronze_payments_raw and bronze_payments_bulk table locations, 8.4)."
  type        = string
}
