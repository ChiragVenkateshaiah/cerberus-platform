# VPC network design per ADR 0007 (3.1/3.3): a dedicated VPC, distinct from
# the account's default 172.31.0.0/16, purpose-built for a spin-up/destroy
# Spark-on-EKS cluster (3.2) rather than standing infrastructure. That
# lifecycle is why this design resolves every Cost-vs-Reliability tension
# toward Cost: a single NAT Gateway instead of one per AZ, and a public EKS
# API endpoint instead of a bastion/VPN this solo project has no other use
# for. Both are accepted gaps, documented in the ADR, not discovered later.
#
# ADR 0011 (5.1): this module holds only the free, always-standing pieces
# (VPC, subnets, IGW, route tables, the S3 gateway endpoint) -- it lives in
# envs/dev-standing, CI-managed. The NAT Gateway + EIP are the one genuinely
# billed piece and are lifecycle-coupled to EKS, not to this module's own
# resources -- they moved to terraform/modules/vpc_nat, applied only from
# envs/dev-compute, human-run per exercise. The private route table here
# declares no inline NAT route for exactly that reason: vpc_nat attaches it
# as a standalone aws_route resource once NAT actually exists, and removes
# it on teardown, without this module ever needing to know NAT exists.
#
# ADR 0024 (9.2) amends ADR 0007 with a third, standalone console subnet and
# its own route table (local route only, no NAT route at rest) for the demo
# console's session host. It is not in local.private_subnets, which feeds
# EKS and the ECS tasks. The S3 gateway endpoint is not attached to it yet;
# that waits for the step that needs it.

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

# NAT Gateway + EIP live in terraform/modules/vpc_nat (envs/dev-compute) --
# see this file's header note (ADR 0011). This route table intentionally
# declares no inline `route` block for the NAT path; vpc_nat attaches it as
# a standalone aws_route resource against private_route_table_id below once
# NAT actually exists, and destroys it again on teardown.

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

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

# --- Console subnet (ADR 0024): the demo console's session host. Same AZ as
# public-a, where a session NAT would sit, so there is no cross-AZ NAT
# traffic. CloudFront VPC origins do not support use1-az3, and CI is denied
# ec2:DescribeAvailabilityZones, so the AZ ID is checked after creation
# instead of through a data source. ---

resource "aws_subnet" "console" {
  vpc_id                  = aws_vpc.this.id
  availability_zone       = var.console_availability_zone
  cidr_block              = var.console_subnet_cidr
  map_public_ip_on_launch = false

  tags = {
    Name  = "cerberus-platform-console"
    Phase = "9"
  }

  lifecycle {
    postcondition {
      condition     = self.availability_zone_id != "use1-az3"
      error_message = "CloudFront VPC origins do not support use1-az3. Choose another availability zone for the console subnet."
    }
  }
}

# No routes: local traffic only until a session adds a NAT route.
resource "aws_route_table" "console" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name  = "cerberus-platform-console-rt"
    Phase = "9"
  }
}

resource "aws_route_table_association" "console" {
  subnet_id      = aws_subnet.console.id
  route_table_id = aws_route_table.console.id
}
