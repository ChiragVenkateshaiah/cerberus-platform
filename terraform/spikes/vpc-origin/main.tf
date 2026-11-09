# 9.2 VPC-origin spike (ADR 0024 build step 3;
# docs/plans/2026-10-27-vpc-origin-spike.md).
#
# Measures how long a CloudFront VPC origin plus its distribution take to
# create and destroy, and proves the whole path works: CloudFront -> VPC
# origin -> instance SG (inbound only from CloudFront-VPCOrigins-Service-SG)
# -> HTTP responder on a t4g.nano in a private subnet. Two apply/destroy
# cycles; nothing stays behind. Not a real root: local state, see
# versions.tf.

locals {
  name = "cerberus-vpc-origin-spike"

  # Role and instance profile name: matches the cerberus-console-grafana*
  # PassRole / instance-profile grants of cerberus-admin (9.2 IAM).
  role_name = "cerberus-console-grafana-spike"

  # AWS managed CloudFront policies. Fixed IDs, see
  # https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html
  # and .../using-managed-origin-request-policies.html
  cache_policy_caching_disabled    = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  origin_request_policy_all_viewer = "216adef6-5c7f-47e4-b989-5492eafa07d3"

  self_terminate_minutes = 120
}

data "aws_vpc" "this" {
  tags = {
    Name = "cerberus-platform-vpc"
  }
}

data "aws_subnet" "private_a" {
  vpc_id = data.aws_vpc.this.id

  tags = {
    Name = "cerberus-platform-private-a"
  }

  lifecycle {
    postcondition {
      condition     = self.availability_zone_id != "use1-az3"
      error_message = "CloudFront VPC origins do not support use1-az3."
    }
  }
}

data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

# No policies: the instance calls no AWS API. The role and profile exist to
# retire the PassRole / instance-profile part of 9.2 IAM risk 1.
resource "aws_iam_role" "this" {
  name = local.role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_instance_profile" "this" {
  name = local.role_name
  role = aws_iam_role.this.name
}

# No inline ingress or egress blocks: the provider revokes the default
# allow-all egress, so the group has zero egress rules. The only rule is the
# separate ingress rule below.
resource "aws_security_group" "this" {
  name        = local.name
  description = "9.2 spike: HTTP inbound from the CloudFront VPC origin only"
  vpc_id      = data.aws_vpc.this.id

  tags = {
    Name = local.name
  }
}

resource "aws_instance" "this" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.insecure_value
  instance_type               = "t4g.nano"
  subnet_id                   = data.aws_subnet.private_a.id
  vpc_security_group_ids      = [aws_security_group.this.id]
  iam_instance_profile        = aws_iam_instance_profile.this.name
  associate_public_ip_address = false

  # The instance terminates itself (shutdown -h in user data); the 2-hour
  # timer is the backstop for the only hourly-billed resource.
  instance_initiated_shutdown_behavior = "terminate"

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    responder_b64          = base64encode(file("${path.module}/responder.py"))
    self_terminate_minutes = local.self_terminate_minutes
  })
  user_data_replace_on_change = true

  tags = {
    Name = local.name
  }
}

resource "aws_cloudfront_vpc_origin" "this" {
  vpc_origin_endpoint_config {
    name                   = local.name
    arn                    = aws_instance.this.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  # Creation "can take up to 15 minutes" (AWS docs); delete time is unknown.
  timeouts {
    create = "30m"
    update = "30m"
    delete = "30m"
  }
}

# CloudFront creates this group together with the VPC origin; an inbound rule
# that references it can be added only after the VPC origin exists. The group
# is AWS-managed: read it, never edit or delete it.
data "aws_security_group" "cloudfront_vpc_origins" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.this.id]
  }

  filter {
    name   = "group-name"
    values = ["CloudFront-VPCOrigins-Service-SG*"]
  }

  depends_on = [aws_cloudfront_vpc_origin.this]
}

resource "aws_vpc_security_group_ingress_rule" "from_cloudfront" {
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = data.aws_security_group.cloudfront_vpc_origins.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
  description                  = "CloudFront VPC origin only"
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  comment             = "cerberus vpc-origin spike"
  price_class         = "PriceClass_100"
  wait_for_deployment = true

  origin {
    origin_id   = "spike"
    domain_name = aws_instance.this.private_dns

    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.this.id
    }
  }

  default_cache_behavior {
    target_origin_id         = "spike"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    viewer_protocol_policy   = "redirect-to-https"
    cache_policy_id          = local.cache_policy_caching_disabled
    origin_request_policy_id = local.origin_request_policy_all_viewer
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  depends_on = [aws_vpc_security_group_ingress_rule.from_cloudfront]
}
