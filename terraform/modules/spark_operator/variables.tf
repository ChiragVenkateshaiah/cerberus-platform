variable "operator_namespace" {
  description = "Namespace the Spark Operator's controller/webhook run in."
  type        = string
  default     = "spark-operator"
}

variable "jobs_namespace" {
  description = "Namespace the operator watches for SparkApplication resources -- where 3.5's job and its IRSA-bound service account will live. Deliberately not the chart's own default of 'default'."
  type        = string
  default     = "spark-jobs"
}

variable "chart_version" {
  description = "spark-operator Helm chart version. Left unset (null) so Helm installs the current latest -- this cluster is spun up and destroyed per job (3.7), so there's no long-lived pin to protect against upgrade drift, and no verified current version to hardcode confidently."
  type        = string
  default     = null
}
