output "dashboard_name" {
  description = "The pipeline CloudWatch dashboard's name."
  value       = aws_cloudwatch_dashboard.pipeline.dashboard_name
}

output "dashboard_url" {
  description = "Console URL for the pipeline dashboard."
  value       = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards/dashboard/${aws_cloudwatch_dashboard.pipeline.dashboard_name}"
}

output "freshness_probe_function_name" {
  description = "The freshness probe Lambda's function name -- for a manual `aws lambda invoke` to force a first datapoint."
  value       = aws_lambda_function.probe.function_name
}

output "freshness_metric_namespace" {
  description = "CloudWatch namespace the freshness probe publishes to -- Phase 6.2's alarms read FreshnessSeconds{Signal} here."
  value       = "Cerberus/Pipeline"
}
