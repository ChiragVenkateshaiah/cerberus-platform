# No secrets here.

output "domain_name" {
  description = "The distribution's domain name."
  value       = module.launch_edge.domain_name
}

output "distribution_id" {
  description = "The distribution ID."
  value       = module.launch_edge.distribution_id
}

output "key_group_id" {
  description = "The key group ID that signs every behaviour."
  value       = module.launch_edge.key_group_id
}

output "build_bucket" {
  description = "Build bucket name."
  value       = module.launch_edge.build_bucket
}

output "log_bucket" {
  description = "Log bucket name."
  value       = module.launch_edge.log_bucket
}

output "instance_id" {
  description = "The load generator instance ID, or null when create_load_gen is false."
  value       = module.launch_edge.instance_id
}

output "kvs_arn" {
  description = "ARN of the release KeyValueStore."
  value       = module.launch_edge.kvs_arn
}

output "public_key_id" {
  description = "The CloudFront public key ID (Key-Pair-Id of the signed cookies)."
  value       = module.launch_edge.public_key_id
}

output "origin_metric_filter" {
  description = "S3 request metrics filter ID for patch/ (ADR 0030 Decision 15)."
  value       = module.launch_edge.origin_metric_filter
}
