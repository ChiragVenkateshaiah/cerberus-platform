variable "bucket_arns" {
  description = "Map of layer -> bucket ARN (bronze/silver only needed here), read from envs/dev-standing's state via terraform_remote_state -- not a direct module reference."
  type        = map(string)
}

variable "eks_oidc_provider_arn" {
  description = "IAM OIDC provider ARN from the eks module (this root's own module.eks, envs/dev-compute)."
  type        = string
}

variable "eks_oidc_issuer_url" {
  description = "EKS cluster's OIDC issuer URL from the eks module (with https:// scheme), used to scope the IRSA trust policy's sub/aud conditions."
  type        = string
}

variable "spark_service_account" {
  description = "Kubernetes service account (namespace:name) allowed to assume cerberus-spark via IRSA."
  type        = string
  default     = "spark-jobs:cerberus-spark"
}

variable "glue_database_name" {
  description = "Glue database holding silver's Iceberg table (8.5)."
  type        = string
  default     = "cerberus_platform"
}

variable "silver_table_name" {
  description = "The Iceberg silver table cerberus-spark commits to (8.5, ADR 0017)."
  type        = string
  default     = "payments_events"
}
