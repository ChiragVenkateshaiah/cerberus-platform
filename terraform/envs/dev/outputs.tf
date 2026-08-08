output "bucket_names" {
  description = "Map of layer -> bucket name."
  value       = module.s3_medallion.bucket_names
}

output "bucket_arns" {
  description = "Map of layer -> bucket ARN."
  value       = module.s3_medallion.bucket_arns
}

output "role_arns" {
  description = "Map of role name -> ARN (ingestion/transform/serving)."
  value       = module.iam.role_arns
}
