variable "cluster_name" {
  description = "EKS cluster name -- auto-discovery and the IAM scoping both key on it."
  type        = string
}

variable "kubernetes_version" {
  description = "The cluster's Kubernetes minor version (e.g. 1.33), from the eks module; the autoscaler image tag is v<minor>.0."
  type        = string
}

variable "eks_oidc_provider_arn" {
  description = "The cluster's IAM OIDC provider, for the IRSA trust policy."
  type        = string
}

variable "eks_oidc_issuer_url" {
  description = "The cluster's OIDC issuer URL, for the IRSA trust-policy conditions."
  type        = string
}

variable "namespace" {
  description = "Namespace for the autoscaler."
  type        = string
  default     = "kube-system"
}

variable "chart_version" {
  description = "kubernetes/autoscaler cluster-autoscaler chart version. Pinned like the monitoring charts; the image tag is set separately to match the cluster."
  type        = string
  default     = "9.59.0"
}
