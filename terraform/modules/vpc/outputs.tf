output "vpc_id" {
  description = "The VPC ID, for the eks module's cluster/node-group placement."
  value       = aws_vpc.this.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (a, b) -- where EKS worker nodes (3.2) and the control plane's cross-account ENIs live."
  value       = [for k in ["a", "b"] : aws_subnet.private[k].id]
}

output "public_subnet_ids" {
  description = "Public subnet IDs (a, b). public-a hosts the NAT Gateway; public-b is reserved, unused by this phase's design."
  value       = [for k in ["a", "b"] : aws_subnet.public[k].id]
}
