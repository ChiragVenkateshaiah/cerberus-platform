# Split out of terraform/modules/vpc by ADR 0011 (5.1): the NAT Gateway +
# EIP are the one genuinely billed piece of the VPC, and lifecycle-coupled
# to EKS (both come up for a Spark exercise and are destroyed together
# afterward -- see checkpoint.md's Notes/blockers destroy-target list),
# not to the free VPC/subnet/routing resources that stay standing across
# that cycle. This module is applied only from envs/dev-compute, alongside
# eks/spark_operator/spark_job -- never from envs/dev-standing, and never
# by CI.
#
# vpc_id/public_subnet_id/private_route_table_id all come from
# envs/dev-standing's state via a terraform_remote_state data source (see
# envs/dev-compute/main.tf) -- this module has no direct reference to the
# vpc module's resources, only to its already-applied outputs. That's a
# one-directional read (compute depends on standing, never the reverse),
# the same shape as spark_job's existing orchestration_transform_role_arn
# dependency.
#
# A NAT failure is retriable (terraform destroy + re-apply rebuilds this
# module from code) since this VPC only exists for the duration of one
# Spark job, not as always-on infrastructure that needs to survive an
# outage while idle -- ADR 0007's original Cost-over-Reliability framing,
# unchanged by this module split.

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name  = "cerberus-platform-nat-eip"
    Phase = "3"
  }
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = var.public_subnet_id

  tags = {
    Name  = "cerberus-platform-nat"
    Phase = "3"
  }
}

# Standalone aws_route, not an inline `route` block on the vpc module's
# route table resource -- that table lives in a different state
# (envs/dev-standing) and must stay valid whether or not this module (and
# NAT) currently exist. Attaching the route externally is the standard
# Terraform pattern for "a route table owned elsewhere, a route owned here."
resource "aws_route" "private_nat" {
  route_table_id         = var.private_route_table_id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}
