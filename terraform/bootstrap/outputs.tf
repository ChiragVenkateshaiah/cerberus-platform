output "state_bucket_name" {
  description = "S3 bucket holding Terraform remote state."
  value       = aws_s3_bucket.tfstate.bucket
}

output "state_bucket_arn" {
  description = "ARN of the Terraform state bucket."
  value       = aws_s3_bucket.tfstate.arn
}

output "lock_table_name" {
  description = "DynamoDB table used for Terraform state locking."
  value       = aws_dynamodb_table.tfstate_lock.name
}

output "lock_table_arn" {
  description = "ARN of the Terraform state lock table."
  value       = aws_dynamodb_table.tfstate_lock.arn
}
