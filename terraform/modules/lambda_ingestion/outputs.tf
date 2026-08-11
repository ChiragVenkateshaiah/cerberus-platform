output "function_name" {
  description = "The ingestion Lambda's function name."
  value       = aws_lambda_function.ingest_payments.function_name
}

output "function_arn" {
  description = "The ingestion Lambda's ARN."
  value       = aws_lambda_function.ingest_payments.arn
}

output "schedule_name" {
  description = "The EventBridge Scheduler schedule name."
  value       = aws_scheduler_schedule.daily.name
}
