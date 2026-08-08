variable "bucket_arns" {
  description = "Map of layer -> bucket ARN (bronze/silver/gold), from the s3_medallion module."
  type        = map(string)
}

variable "trusted_principal_arn" {
  description = "IAM principal ARN allowed to assume all three roles (sts:AssumeRole). Today: cerberus-admin, the only identity in this account -- future phases (2.3's Lambda, etc.) get their own trust policies when they exist."
  type        = string
}
