output "bucket_names" {
  description = "Map of layer -> bucket name."
  value       = { for k, v in aws_s3_bucket.this : k => v.bucket }
}

output "bucket_arns" {
  description = "Map of layer -> bucket ARN."
  value       = { for k, v in aws_s3_bucket.this : k => v.arn }
}
