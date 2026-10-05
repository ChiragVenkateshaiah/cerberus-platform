variable "namespace" {
  description = "Namespace the Prometheus agent, its kube-state-metrics / node-exporter subcharts, and Grafana run in."
  type        = string
  default     = "monitoring"
}

variable "region" {
  description = "AWS region -- SigV4 signing region for AMP remote-write and Grafana's AMP/CloudWatch data sources."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name, attached to every sample as the `cluster` external label."
  type        = string
}

variable "eks_oidc_provider_arn" {
  description = "IAM OIDC provider ARN from this root's module.eks -- both IRSA roles federate through it."
  type        = string
}

variable "eks_oidc_issuer_url" {
  description = "EKS cluster's OIDC issuer URL (with https:// scheme), used to scope both IRSA trust policies' sub/aud conditions."
  type        = string
}

variable "amp_workspace_arn" {
  description = "AMP workspace ARN, read from envs/dev-standing's state -- the one resource both IRSA roles' aps:* grants are scoped to."
  type        = string
}

variable "amp_remote_write_url" {
  description = "AMP remote-write URL, read from envs/dev-standing's state."
  type        = string
}

variable "amp_prometheus_endpoint" {
  description = "AMP workspace's Prometheus-compatible base URL, read from envs/dev-standing's state -- Grafana's AMP data source points here."
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

variable "grafana_chart_version" {
  description = "grafana-community/grafana chart version (app 13.2.3). Grafana's charts moved from grafana/helm-charts to grafana-community/helm-charts; the old repo stopped at 10.5.x. Pinned for the same reason as the Prometheus chart."
  type        = string
  default     = "13.2.7"
}

variable "amp_plugin_version" {
  description = "grafana-amazonprometheus-datasource plugin version. 3.2.0 requires Grafana >= 12.2.5, which the pinned chart's 13.2.3 satisfies."
  type        = string
  default     = "3.2.0"
}
