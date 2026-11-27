# The Spot load generator (ADR 0030 Decision 6). PREWARM has no instance:
# create_load_gen defaults to false and every resource here has count 0.
# 17.4: the k6 pin (k6_version, k6_sha256), the nftables byte budget
# (budget_bytes) and the self-run from user data (no SendCommand path exists).
#
# Security review 2026-11-25 (docs/plans/2026-11-25-launch-edge.md):
# - the role does NOT attach AmazonSSMManagedInstanceCore, which reads any SSM
#   parameter; the inline policy lists the Session Manager actions and one
#   parameter;
# - instance and volumes carry Project at RunInstances (terminate and
#   StartSession are denied without it);
# - one-time Spot with terminate on interruption (StopInstances is denied);
# - the instance profile has a fixed name, set at launch
#   (AssociateIamInstanceProfile and ListInstanceProfiles are denied).

locals {
  gen_name         = "cerberus-launch-loadgen"
  gen_count        = var.create_load_gen ? 1 : 0
  shutdown_minutes = var.minutes + var.shutdown_margin_minutes
  cookie_param_arn = "arn:aws:ssm:${var.region}:${var.account_id}:parameter${var.cookie_parameter_name}"
}

resource "aws_iam_role" "load_gen" {
  count = local.gen_count
  name  = local.gen_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "load_gen" {
  count = local.gen_count
  name  = local.gen_name
  role  = aws_iam_role.load_gen[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The one session-cookie parameter, created outside Terraform.
        Sid      = "ReadSessionCookies"
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = local.cookie_param_arn
      },
      {
        # Seed writes: the generator uploads the content it then downloads.
        Sid      = "SeedWrites"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = ["${aws_s3_bucket.build.arn}/build/*", "${aws_s3_bucket.build.arn}/patch/*"]
      },
      {
        # Beyond ADR 0030 Decision 6 ("seed writes"): the generator writes the
        # k6 summaries and the seeded/done markers under results/. Nothing else.
        # Added in 17.4 because the admin policy has no SendCommand; the owner
        # decides on it (escalate: opus-security).
        Sid      = "ResultsWrite"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.build.arn}/results/*"
      },
      {
        Sid      = "ReadScenarios"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.build.arn}/scenarios/*"
      },
      {
        Sid      = "ListScenarios"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.build.arn
        Condition = {
          StringLike = { "s3:prefix" = ["scenarios/", "scenarios/*"] }
        }
      },
      {
        # What the SSM agent needs for Session Manager and registration. These
        # are the actions of AmazonSSMManagedInstanceCore minus every
        # ssm:GetParameter* and the other broad reads.
        Sid    = "SessionManagerAgent"
        Effect = "Allow"
        Action = [
          "ssm:UpdateInstanceInformation",
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "load_gen" {
  count = local.gen_count
  name  = local.gen_name
  role  = aws_iam_role.load_gen[0].name
}

# No ingress. Egress is HTTPS only: the VPC resolver is not filtered by a
# security group (same note as dev-console). 17.4 checked this against the
# existing rules and added no port 53 rule: k6 per-client DNS (ttl 0, random
# select) uses the VPC resolver. If Run A shows lookups failing, add tcp and udp
# 53 egress then (unverified until Run A).
resource "aws_security_group" "load_gen" {
  count       = local.gen_count
  name        = local.gen_name
  description = "Launch load generator: no ingress, 443 out"
  vpc_id      = var.vpc_id

  tags = {
    Name = local.gen_name
  }
}

resource "aws_vpc_security_group_egress_rule" "load_gen_https" {
  count             = local.gen_count
  security_group_id = aws_security_group.load_gen[0].id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
  description       = "HTTPS out: CloudFront, S3 and AWS APIs"
}

# Read only when the instance exists, so PREWARM needs no SSM read.
data "aws_ssm_parameter" "al2023_arm64" {
  count = local.gen_count
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "load_gen" {
  count = local.gen_count

  ami                         = data.aws_ssm_parameter.al2023_arm64[0].insecure_value
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.load_gen[0].id]
  iam_instance_profile        = aws_iam_instance_profile.load_gen[0].name
  associate_public_ip_address = true

  # `shutdown -h` in user data is the backstop if the session trap dies.
  # No instance_initiated_shutdown_behavior: EC2 refuses it for Spot
  # ("Modifying 'instanceInitiatedShutdownBehavior' is not supported for spot
  # instances", Run A 2026-11-27). A one-time Spot instance cannot be stopped,
  # so an OS shutdown is expected to terminate it (unverified; Run A checks).

  instance_market_options {
    market_type = "spot"

    spot_options {
      spot_instance_type             = "one-time"
      instance_interruption_behavior = "terminate"
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    shutdown_minutes = local.shutdown_minutes
    minutes          = var.minutes
    region           = var.region
    build_bucket     = aws_s3_bucket.build.bucket
    cookie_parameter = var.cookie_parameter_name
    domain_name      = aws_cloudfront_distribution.this.domain_name
    k6_version       = var.k6_version
    k6_sha256        = var.k6_sha256
    budget_bytes     = var.budget_bytes
  })
  user_data_replace_on_change = true

  # Project must be on the instance and its volumes at RunInstances: the
  # cerberus-admin terminate and StartSession grants test it.
  tags        = merge(local.tags, { Name = local.gen_name })
  volume_tags = merge(local.tags, { Name = local.gen_name })

  # Fail closed: an instance with no byte budget never starts.
  lifecycle {
    precondition {
      condition     = var.budget_bytes > 0
      error_message = "budget_bytes must be above 0 when the load generator is created (launch/plan_bytes.py prints it)."
    }
  }

  depends_on = [aws_iam_role_policy.load_gen]
}
