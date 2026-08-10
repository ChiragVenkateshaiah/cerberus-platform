output "workgroup_name" {
  description = "Athena workgroup name."
  value       = aws_athena_workgroup.this.name
}

output "results_bucket_name" {
  description = "Athena query-results bucket name."
  value       = aws_s3_bucket.results.bucket
}

output "results_bucket_arn" {
  description = "Athena query-results bucket ARN."
  value       = aws_s3_bucket.results.arn
}
