variable "bucket_arns" {
  description = "Map of layer -> bucket ARN (bronze/silver/gold), from the s3_medallion module."
  type        = map(string)
}

variable "trusted_principal_arn" {
  description = "IAM principal ARN allowed to assume all three roles (sts:AssumeRole). Today: cerberus-admin, the only identity in this account -- future phases (2.3's Lambda, etc.) get their own trust policies when they exist."
  type        = string
}

variable "account_id" {
  description = "AWS account ID, used to build Glue Catalog ARNs."
  type        = string
}

variable "region" {
  description = "AWS region, used to build Glue Catalog ARNs."
  type        = string
  default     = "us-east-1"
}

variable "glue_database_name" {
  description = "Glue database holding the payments tables."
  type        = string
}

variable "glue_table_names" {
  description = "Glue table names (payments_events, payments_current) that cerberus-serving gets read access to."
  type        = list(string)
}

variable "glue_partition_table_name" {
  description = "The single Glue table (payments_events) that cerberus-transform registers partitions against."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup name, used to build its ARN for cerberus-transform's query-execution permissions."
  type        = string
}

variable "athena_results_bucket_arn" {
  description = "Athena query-results bucket ARN, from the athena module."
  type        = string
}

variable "eks_oidc_provider_arn" {
  description = "IAM OIDC provider ARN from the eks module, for the Spark job's IRSA-federated role."
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

# 4.2: built from a literal name, not module.eks.cluster_name -- taking
# the eks module's output here would make this module depend on eks,
# while eks's own access entry (for orchestration_transform's role,
# defined below) needs this module's role ARN, which would create a
# module dependency cycle. The default matches the eks module's own
# cluster_name default; the root module passes both from one shared
# local so they can't drift independently.
variable "eks_cluster_name" {
  description = "EKS cluster name, used only to build its ARN for cerberus-orchestration-transform's eks:DescribeCluster grant."
  type        = string
  default     = "cerberus-platform-eks"
}
