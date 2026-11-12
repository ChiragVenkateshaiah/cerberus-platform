# ADR 0024 build step 10, PR D: the per-session live Grafana
# (docs/plans/2026-11-12-console-session.md). The third root, with the
# dev-compute contract: human-run from the owner's terminal, never planned or
# applied by CI, destroy leaves nothing billable.
#
# Files: main.tf (host: NAT, role, SG, instance), edge.tf (VPC origin,
# distribution, Cognito client), session.tf (bundle, readiness probe,
# live.json), user_data.sh.tftpl (the boot script). README.md has the flow.

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# Reads envs/dev-standing's already-applied outputs, one-directional (console
# depends on standing, never the reverse). The bucket name is built from the
# account ID so that no committed file carries it.
data "terraform_remote_state" "standing" {
  backend = "s3"

  config = {
    bucket = "cerberus-platform-tfstate-${data.aws_caller_identity.current.account_id}"
    key    = "envs/dev-standing/terraform.tfstate"
    region = "us-east-1"
  }
}

locals {
  name = "cerberus-console-grafana"

  standing = data.terraform_remote_state.standing.outputs

  # Names the instance's boot script and the bundle agree on.
  dashboards_dir = "/var/lib/grafana/dashboards/console"

  # Repo root, from terraform/envs/dev-console.
  repo_root = "${path.module}/../../.."

  # Single source of truth for the Grafana and plugin pins (PR B). The boot
  # script gets the key and sha256 from here; it checks the hash again.
  artifacts = {
    for a in jsondecode(file("${local.repo_root}/observability/grafana/console/artifacts.json")).artifacts :
    a.name => a
  }
  grafana_artifact = local.artifacts["grafana"]
  plugin_artifact  = local.artifacts["grafana-amazonprometheus-datasource"]

  # The instance shuts itself down this long after boot: the session, plus
  # about 15 minutes of wake (spike F6: wake 11:52 to 15:35) and slack.
  # Value from the plan (§5: boot + MINUTES + 30).
  shutdown_minutes = var.minutes + 30

  # time_static.started is the moment the readiness probe passed.
  ends = timeadd(time_static.started.rfc3339, "${var.minutes}m")
}

# --- 1. NAT, on the console route table only --------------------------------
# Grafana's server must reach the Cognito hosted-UI token endpoint (ADR 0024
# L196-198), so the console subnet gets a NAT for the length of a session. The
# module is the one dev-compute uses; it only needs a subnet and a route
# table, and takes the console ones.
module "nat" {
  source = "../../modules/vpc_nat"

  public_subnet_id       = local.standing.public_subnet_a_id
  private_route_table_id = local.standing.console_route_table_id
}

# --- 2. IAM -----------------------------------------------------------------
# Names match the cerberus-console-grafana* PassRole and instance-profile
# grants of cerberus-admin (spike plan F7).
resource "aws_iam_role" "grafana" {
  name = local.name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "grafana" {
  name = local.name
  role = aws_iam_role.grafana.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The AMP plugin signs its queries with this role (sigV4AuthType
        # default). Query only: no write, no workspace admin.
        Sid    = "QueryAmp"
        Effect = "Allow"
        Action = [
          "aps:QueryMetrics",
          "aps:GetSeries",
          "aps:GetLabels",
          "aps:GetMetricMetadata",
        ]
        Resource = local.standing.prometheus_workspace_arn
      },
      {
        # The pinned Grafana and plugin packages and the per-session bundle.
        # The prefix is private: CloudFront is denied it by the bucket policy.
        Sid      = "ReadArtifacts"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:aws:s3:::${local.standing.console_site_bucket_name}/artifacts/*"
      },
      {
        # Plan option 4.2 A: the instance reads its own app client (ID,
        # secret, callback URL) at boot. The secret never touches S3, tags or
        # user data. Gives up: the role can read every client in the pool (the
        # SPA client is public, it has no secret).
        Sid    = "ReadOwnAppClient"
        Effect = "Allow"
        Action = [
          "cognito-idp:ListUserPoolClients",
          "cognito-idp:DescribeUserPoolClient",
        ]
        Resource = "arn:aws:cognito-idp:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:userpool/${local.standing.console_user_pool_id}"
      },
    ]
  })
}

# SSM Session Manager is the only way in for debugging (no SSH, no key pair).
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "grafana" {
  name = local.name
  role = aws_iam_role.grafana.name
}

# --- 3. Security group ------------------------------------------------------
# No inline rules: the provider revokes the default allow-all egress, so only
# the two rule resources below exist. Name matches console_check.sh (PR E).
resource "aws_security_group" "grafana" {
  name        = local.name
  description = "Console Grafana: 3000 from the CloudFront VPC origin only, 443 out"
  vpc_id      = local.standing.vpc_id

  tags = {
    Name = local.name
  }
}

# Cognito hosted UI, the AWS APIs and the S3 artifacts. The Route 53 resolver
# and IMDS are not filtered by security groups.
resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.grafana.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
  description       = "HTTPS out via the session NAT"
}

# Only CloudFront-VPCOrigins-Service-SG may reach Grafana. That group exists
# only after the VPC origin does; see edge.tf.
resource "aws_vpc_security_group_ingress_rule" "from_cloudfront" {
  security_group_id            = aws_security_group.grafana.id
  referenced_security_group_id = data.aws_security_group.cloudfront_vpc_origins.id
  ip_protocol                  = "tcp"
  from_port                    = 3000
  to_port                      = 3000
  description                  = "CloudFront VPC origin only"
}

# --- 4. The Grafana host ----------------------------------------------------
data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "grafana" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.insecure_value
  instance_type               = "t4g.small"
  subnet_id                   = local.standing.console_subnet_id
  vpc_security_group_ids      = [aws_security_group.grafana.id]
  iam_instance_profile        = aws_iam_instance_profile.grafana.name
  associate_public_ip_address = false

  # `shutdown -h` in user data ends the session host (and its bill) even if
  # the owner's terminal dies. Do not set credit_specification: T4g defaults
  # to unlimited, the surplus for a short session is estimated at about $0.01
  # (unverified), and ec2:ModifyInstanceCreditSpecification is implicitly
  # denied for cerberus-admin (plan F24).
  instance_initiated_shutdown_behavior = "terminate"

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    shutdown_minutes = local.shutdown_minutes
    region           = data.aws_region.current.name
    bucket           = local.standing.console_site_bucket_name
    user_pool_id     = local.standing.console_user_pool_id
    # console_auth_domain is a base URL; grafana.ini.tmpl wants the host.
    cognito_domain = replace(local.standing.console_auth_domain, "https://", "")
    amp_url        = local.standing.prometheus_endpoint
    dashboards_dir = local.dashboards_dir
    client_name    = local.name

    grafana_key    = local.grafana_artifact.key
    grafana_sha256 = local.grafana_artifact.sha256
    plugin_id      = local.plugin_artifact.name
    plugin_key     = local.plugin_artifact.key
    plugin_sha256  = local.plugin_artifact.sha256
    bundle_key     = aws_s3_object.bundle.key
    bundle_sha256  = data.archive_file.bundle.output_sha256
  })
  user_data_replace_on_change = true

  tags = {
    Name = local.name
  }

  # The NAT route must exist before boot: the script reaches Cognito and the
  # AWS APIs through it. (module.nat includes its aws_route). The role policy
  # must exist too, or the first AWS calls at boot would be denied.
  depends_on = [module.nat, aws_iam_role_policy.grafana]
}
