variable "github_owner" {
  description = "GitHub org/user that owns the repo -- scopes the OIDC trust policy's sub claim."
  type        = string
  default     = "ChiragVenkateshaiah"
}

variable "github_repo" {
  description = "GitHub repo name -- scopes the OIDC trust policy's sub claim."
  type        = string
  default     = "cerberus-platform"
}

variable "account_id" {
  description = "AWS account ID, used to build resource ARNs for cerberus-ci-apply's scoped policy."
  type        = string
}

variable "region" {
  description = "AWS region, used to build resource ARNs for cerberus-ci-apply's scoped policy."
  type        = string
  default     = "us-east-1"
}

variable "tfstate_bucket_arn" {
  description = "Terraform state bucket ARN (bootstrap-managed) -- both CI roles need scoped access to read/write envs/dev-standing's own state object."
  type        = string
}

variable "tfstate_lock_table_arn" {
  description = "Terraform state lock DynamoDB table ARN (bootstrap-managed)."
  type        = string
}

variable "bucket_arns" {
  description = "Map of layer -> bucket ARN (bronze/silver/gold), from the s3_medallion module -- cerberus-ci-apply gets full S3 access scoped to exactly these buckets."
  type        = map(string)
}

variable "athena_results_bucket_arn" {
  description = "Athena query-results bucket ARN, from the athena module -- a separate bucket from bucket_arns' bronze/silver/gold, also managed by envs/dev-standing so cerberus-ci-apply needs access to it too."
  type        = string
}
