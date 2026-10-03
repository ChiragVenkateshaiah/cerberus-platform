output "workspace_id" {
  description = "AMP workspace ID (ws-...)."
  value       = aws_prometheus_workspace.this.id
}

output "workspace_arn" {
  description = "AMP workspace ARN -- the resource the dev-compute IRSA roles' aps:RemoteWrite / aps:Query* grants are scoped to."
  value       = aws_prometheus_workspace.this.arn
}

output "prometheus_endpoint" {
  description = "The workspace's Prometheus-compatible base URL (ends in '/'). Grafana's AMP data source points here; PromQL queries go to <endpoint>api/v1/query."
  value       = aws_prometheus_workspace.this.prometheus_endpoint
}

output "remote_write_url" {
  description = "The URL the in-cluster Prometheus agent remote_writes to."
  value       = "${aws_prometheus_workspace.this.prometheus_endpoint}api/v1/remote_write"
}
