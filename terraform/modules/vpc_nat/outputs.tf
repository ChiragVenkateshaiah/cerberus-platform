output "nat_gateway_id" {
  description = "NAT Gateway ID, for reference/verification."
  value       = aws_nat_gateway.this.id
}
