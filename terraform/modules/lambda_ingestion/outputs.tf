output "function_name" {
  description = "The ingestion Lambda's function name."
  value       = aws_lambda_function.ingest_payments.function_name
}

output "function_arn" {
  description = "The ingestion Lambda's ARN."
  value       = aws_lambda_function.ingest_payments.arn
}
