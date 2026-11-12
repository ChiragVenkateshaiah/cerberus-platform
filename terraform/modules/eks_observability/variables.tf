variable "namespace" {
  description = "Namespace the Prometheus agent, its kube-state-metrics / node-exporter subcharts and the Spark progress exporter run in."
  type        = string
  default     = "monitoring"
}

variable "region" {
  description = "AWS region -- SigV4 signing region for AMP remote-write."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name, attached to every sample as the `cluster` external label."
  type        = string
}

variable "eks_oidc_provider_arn" {
  description = "IAM OIDC provider ARN from this root's module.eks -- the cerberus-prometheus IRSA role federates through it."
  type        = string
}

variable "eks_oidc_issuer_url" {
  description = "EKS cluster's OIDC issuer URL (with https:// scheme), used to scope the cerberus-prometheus IRSA trust policy's sub/aud conditions."
  type        = string
}

variable "amp_workspace_arn" {
  description = "AMP workspace ARN, read from envs/dev-standing's state -- the one resource the cerberus-prometheus IRSA role's aps:* grant is scoped to."
  type        = string
}

variable "amp_remote_write_url" {
  description = "AMP remote-write URL, read from envs/dev-standing's state."
  type        = string
}

variable "spark_jobs_namespace" {
  description = "Namespace the Spark driver/executor pods run in -- the agent's Spark scrape jobs are limited to it."
  type        = string
}

variable "spark_operator_namespace" {
  description = "Namespace the Spark Operator controller runs in -- the agent scrapes its /metrics there."
  type        = string
}

variable "scrape_interval" {
  description = "Agent scrape interval. 15s, per ADR 0016's ~10k-series estimate."
  type        = string
  default     = "15s"
}

variable "prometheus_chart_version" {
  description = "prometheus-community/prometheus chart version (app v3.15.0). Pinned, unlike spark_operator's chart: the agent-mode flag set below (defaultFlagsOverride) is coupled to the chart's own default args and to Prometheus 3's `--agent` flag, so a silent chart bump could break it."
  type        = string
  default     = "29.35.0"
}

variable "spark_progress_image" {
  description = "Image for the Spark progress exporter (6c). The Spark image already used for jobs: it ships python3 3.10, and the exporter is stdlib only. Same tag as spark_operator's spark_image."
  type        = string
  default     = "apache/spark:3.5.9"
}
