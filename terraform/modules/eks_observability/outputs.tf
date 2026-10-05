output "namespace" {
  description = "Namespace Prometheus and Grafana run in."
  value       = kubernetes_namespace.monitoring.metadata[0].name
}

output "prometheus_role_arn" {
  description = "cerberus-prometheus IRSA role ARN (aps:RemoteWrite only)."
  value       = aws_iam_role.prometheus.arn
}

output "grafana_role_arn" {
  description = "cerberus-grafana IRSA role ARN (AMP query + CloudWatch read)."
  value       = aws_iam_role.grafana.arn
}

output "grafana_port_forward" {
  description = "How to reach Grafana (ADR 0016: port-forward only, no Service exposure). Admin password: kubectl get secret -n monitoring grafana -o jsonpath='{.data.admin-password}' | base64 -d"
  value       = "kubectl port-forward -n ${kubernetes_namespace.monitoring.metadata[0].name} svc/grafana 3000:80"
}
