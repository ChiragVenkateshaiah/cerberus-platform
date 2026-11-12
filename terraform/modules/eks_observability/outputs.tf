output "namespace" {
  description = "Namespace the Prometheus agent and the Spark progress exporter run in."
  value       = kubernetes_namespace.monitoring.metadata[0].name
}

output "prometheus_role_arn" {
  description = "cerberus-prometheus IRSA role ARN (aps:RemoteWrite only)."
  value       = aws_iam_role.prometheus.arn
}
