output "domain_name" {
  description = "The distribution's domain name."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  description = "The distribution ID (for the invalidation-free destroy check and BytesDownloaded)."
  value       = aws_cloudfront_distribution.this.id
}

output "key_group_id" {
  description = "The key group ID that signs every behaviour."
  value       = aws_cloudfront_key_group.this.id
}

output "build_bucket" {
  description = "Build bucket name: build/, patch/ (served by CloudFront) and scenarios/ (private)."
  value       = aws_s3_bucket.build.bucket
}

output "log_bucket" {
  description = "Log bucket name: CloudFront standard logs under cdn/."
  value       = aws_s3_bucket.logs.bucket
}

output "instance_id" {
  description = "The load generator instance ID, or null when create_load_gen is false."
  value       = one(aws_instance.load_gen[*].id)
}

output "kvs_arn" {
  description = "ARN of the release KeyValueStore."
  value       = aws_cloudfront_key_value_store.release.arn
}

output "public_key_id" {
  description = "The CloudFront public key ID: the Key-Pair-Id of the signed cookies."
  value       = aws_cloudfront_public_key.this.id
}

output "origin_metric_filter" {
  description = "S3 request metrics filter ID on the build bucket (FilterId dimension for GetRequests and BytesDownloaded, Decision 15)."
  value       = aws_s3_bucket_metric.patch.name
}
