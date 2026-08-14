# VPC network design per ADR 0007 (3.1/3.3): a dedicated VPC, distinct from
# the account's default 172.31.0.0/16, purpose-built for a spin-up/destroy
# Spark-on-EKS cluster (3.2) rather than standing infrastructure. That
# lifecycle is why this design resolves every Cost-vs-Reliability tension
# toward Cost: a single NAT Gateway instead of one per AZ, and a public EKS
# API endpoint instead of a bastion/VPN this solo project has no other use
# for. Both are accepted gaps, documented in the ADR, not discovered later.

locals {
  public_subnets = {
    a = { az = var.availability_zones[0], cidr = var.public_subnet_cidrs[0] }
    b = { az = var.availability_zones[1], cidr = var.public_subnet_cidrs[1] }
  }

  private_subnets = {
    a = { az = var.availability_zones[0], cidr = var.private_subnet_cidrs[0] }
    b = { az = var.availability_zones[1], cidr = var.private_subnet_cidrs[1] }
  }
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name  = "cerberus-platform-vpc"
    Phase = "3"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name  = "cerberus-platform-igw"
    Phase = "3"
  }
}

# --- Public subnets: public-a hosts the NAT Gateway; public-b is reserved
# for a future ALB/second NAT, unused by this phase's design (ADR 0007). ---

resource "aws_subnet" "public" {
  for_each = local.public_subnets

  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.value.az
  cidr_block              = each.value.cidr
  map_public_ip_on_launch = true

  tags = {
    Name  = "cerberus-platform-public-${each.key}"
    Phase = "3"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name  = "cerberus-platform-public-rt"
    Phase = "3"
  }
}

resource "aws_route_table_association" "public" {
  for_each = local.public_subnets

  subnet_id      = aws_subnet.public[each.key].id
  route_table_id = aws_route_table.public.id
}

# --- Private subnets: EKS worker nodes (3.2). Sized /20 for VPC CNI's
# per-pod IP allocation headroom -- see the ADR's Performance Efficiency row.

resource "aws_subnet" "private" {
  for_each = local.private_subnets

  vpc_id            = aws_vpc.this.id
  availability_zone = each.value.az
  cidr_block        = each.value.cidr

  tags = {
    Name  = "cerberus-platform-private-${each.key}"
    Phase = "3"
  }
}

# Single NAT Gateway, provisioned in public-a only -- the Cost-over-
# Reliability trade ADR 0007 names explicitly: a NAT failure is retriable
# (terraform destroy + re-apply rebuilds the whole stack from code) since
# this VPC only exists for the duration of one Spark job, not as always-on
# infrastructure that needs to survive an outage while idle.

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name  = "cerberus-platform-nat-eip"
    Phase = "3"
  }

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public["a"].id

  tags = {
    Name  = "cerberus-platform-nat"
    Phase = "3"
  }

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this.id
  }

  tags = {
    Name  = "cerberus-platform-private-rt"
    Phase = "3"
  }
}

resource "aws_route_table_association" "private" {
  for_each = local.private_subnets

  subnet_id      = aws_subnet.private[each.key].id
  route_table_id = aws_route_table.private.id
}

# S3 Gateway VPC endpoint: free, and removes Spark's dominant traffic
# pattern (bronze reads, silver/gold writes) from the NAT Gateway's billed
# path entirely -- the one unambiguous win in ADR 0007 with no trade-off
# attached.

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name  = "cerberus-platform-s3-endpoint"
    Phase = "3"
  }
}
