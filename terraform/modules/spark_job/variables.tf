variable "namespace" {
  description = "Kubernetes namespace the service account lives in -- the spark_operator module's jobs_namespace output."
  type        = string
}

variable "service_account_name" {
  description = "Kubernetes service account name. Must match the name half of iam's spark_service_account variable (default 'cerberus-spark')."
  type        = string
  default     = "cerberus-spark"
}

variable "role_arn" {
  description = "cerberus-spark IAM role ARN (iam module), granted to this service account via IRSA."
  type        = string
}
