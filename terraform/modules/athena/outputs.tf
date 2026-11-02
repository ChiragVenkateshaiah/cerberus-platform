output "workgroup_name" {
  description = "Athena workgroup name."
  value       = aws_athena_workgroup.this.name
}

output "dq_workgroup_name" {
  description = "Athena workgroup for the data-quality suite (8.6)."
  value       = aws_athena_workgroup.data_quality.name
}

output "results_bucket_name" {
  description = "Athena query-results bucket name."
  value       = aws_s3_bucket.results.bucket
}

output "results_bucket_arn" {
  description = "Athena query-results bucket ARN."
  value       = aws_s3_bucket.results.arn
}

output "console_workgroup_name" {
  description = "Athena workgroup for the demo console's fixed query (9.3)."
  value       = aws_athena_workgroup.console.name
}

output "console_results_prefix" {
  description = "Key prefix of the console's query results in the results bucket."
  value       = "console/"
}
