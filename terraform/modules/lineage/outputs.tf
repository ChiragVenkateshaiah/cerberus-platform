output "collector_url" {
  description = "Full URL the OpenLineage producers POST to (6.4c sets this as OPENLINEAGE_URL / spark.openlineage.transport.url's base). The '/api/v1/lineage' path is appended by the OpenLineage HTTP transport itself."
  value       = aws_apigatewayv2_api.collector.api_endpoint
}

output "collector_endpoint_path" {
  description = "The route the collector serves -- for documentation and the smoke-test curl."
  value       = "${aws_apigatewayv2_api.collector.api_endpoint}/api/v1/lineage"
}

output "bucket_name" {
  description = "The lineage event bucket name."
  value       = aws_s3_bucket.lineage.id
}

output "bucket_arn" {
  description = "The lineage event bucket ARN -- passed to github_oidc so cerberus-ci-apply can manage it."
  value       = aws_s3_bucket.lineage.arn
}

output "collector_function_name" {
  description = "The collector Lambda's function name -- for logs / a manual invoke."
  value       = aws_lambda_function.collector.function_name
}
