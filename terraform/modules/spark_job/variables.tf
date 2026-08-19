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

variable "orchestration_transform_kubernetes_group" {
  description = "Kubernetes group this module's own EKS access entry (below) maps cerberus-orchestration-transform's IAM role to -- this module binds that same group to RBAC permissions on sparkapplications, the resource submit_job.sh's containerized adaptation actually drives. Passed from a root-module local so it's defined in exactly one place."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster name (eks module) -- this module's own aws_eks_access_entry needs it directly; see main.tf's header for why that entry lives here rather than in the eks module."
  type        = string
}

variable "orchestration_transform_role_arn" {
  description = "cerberus-orchestration-transform IAM role ARN (iam module) -- registered as an EKS access entry by this module, same way cerberus-admin already reaches the cluster via the eks module's cluster-creator grant."
  type        = string
}
