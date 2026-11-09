output "domain_name" {
  description = "CloudFront domain of the spike distribution (probe.sh input)."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.this.id
}

output "vpc_origin_id" {
  value = aws_cloudfront_vpc_origin.this.id
}

output "instance_id" {
  value = aws_instance.this.id
}

output "service_sg_id" {
  description = "CloudFront-managed CloudFront-VPCOrigins-Service-SG (not owned by this root)."
  value       = data.aws_security_group.cloudfront_vpc_origins.id
}
