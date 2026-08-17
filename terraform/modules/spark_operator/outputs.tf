output "operator_namespace" {
  description = "Namespace the Spark Operator's controller/webhook run in."
  value       = kubernetes_namespace.operator.metadata[0].name
}

output "jobs_namespace" {
  description = "Namespace the operator watches for SparkApplication resources -- where 3.5's job and service account belong."
  value       = kubernetes_namespace.jobs.metadata[0].name
}
