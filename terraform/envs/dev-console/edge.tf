# The browser path: CloudFront -> VPC origin -> instance SG (inbound only from
# CloudFront-VPCOrigins-Service-SG) -> Grafana on 3000. Reuses the learnings
# of the 9.2 VPC-origin spike (docs/plans/2026-10-27-vpc-origin-spike.md),
# whose directory this PR deletes.

locals {
  origin_id = "grafana"

  # Access and ID tokens last 60 minutes (plan §6 PR D). The refresh token
  # lasts 120 minutes so that a 90-minute session does not force a new
  # sign-in at 60 minutes (ADR 0024: Grafana's login maximum is 2 h).
  token_minutes         = 60
  refresh_token_minutes = 120

  # Hosted-UI callback and logout (ADR 0024 L113; plan §5).
  callback_url = "https://${aws_cloudfront_distribution.this.domain_name}/login/generic_oauth"
  logout_url   = "https://${aws_cloudfront_distribution.this.domain_name}/login"
}

# AWS-managed policies, read by name rather than by hard-coded ID (the same
# style as modules/console_edge).
data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

# --- 1. VPC origin ------------------------------------------------------------
resource "aws_cloudfront_vpc_origin" "this" {
  vpc_origin_endpoint_config {
    name                   = local.name
    arn                    = aws_instance.grafana.arn
    http_port              = 3000
    https_port             = 443
    origin_protocol_policy = "http-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  # A stale service SG from an earlier session must be gone first.
  depends_on = [terraform_data.no_stale_service_sg]

  # Creation "can take up to 15 minutes" (AWS docs). Spike: create 8:05 and
  # 2:08, delete about 7:00.
  timeouts {
    create = "30m"
    update = "30m"
    delete = "30m"
  }
}

# --- 2. The service-SG waits (spike finding 1) -------------------------------
# CloudFront creates CloudFront-VPCOrigins-Service-SG with the VPC origin, a
# new one per origin, and the create call can return before the group exists.
# The spike's cycle 2 failed on a data read that raced it. Two steps, both
# polling by the aws.cloudfront.vpcorigin tag key, at most 10 minutes each:
#   1. before the VPC origin: wait until no such group exists. An earlier
#      session's group lingers a few minutes after its origin is deleted, and
#      would otherwise be mistaken for the new one (create-only, no triggers).
#   2. after the VPC origin: wait until exactly one exists; more than one
#      fails at once. The data source below then reads it.
# Never edit that group.
resource "terraform_data" "no_stale_service_sg" {
  provisioner "local-exec" {
    command = "bash ${path.module}/wait_service_sg.sh"

    environment = {
      VPC_ID      = local.standing.vpc_id
      AWS_REGION  = data.aws_region.current.name
      WANT        = "0"
      MAX_SECONDS = "600"
    }
  }
}

resource "terraform_data" "wait_service_sg" {
  triggers_replace = [aws_cloudfront_vpc_origin.this.id]

  provisioner "local-exec" {
    command = "bash ${path.module}/wait_service_sg.sh"

    environment = {
      VPC_ID      = local.standing.vpc_id
      AWS_REGION  = data.aws_region.current.name
      WANT        = "1"
      MAX_SECONDS = "600"
    }
  }
}

# AWS-managed: read it, never edit or delete it.
data "aws_security_group" "cloudfront_vpc_origins" {
  filter {
    name   = "vpc-id"
    values = [local.standing.vpc_id]
  }

  filter {
    name   = "group-name"
    values = ["CloudFront-VPCOrigins-Service-SG*"]
  }

  filter {
    name   = "tag-key"
    values = ["aws.cloudfront.vpcorigin"]
  }

  depends_on = [terraform_data.wait_service_sg]
}

# --- 3. The distribution ------------------------------------------------------
resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  comment             = "cerberus console session"
  price_class         = "PriceClass_100"
  wait_for_deployment = true

  origin {
    origin_id   = local.origin_id
    domain_name = aws_instance.grafana.private_dns

    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.this.id
    }
  }

  # Every method, nothing cached: Grafana is an app (POST /api/ds/query,
  # the Live WebSocket), and AllViewer passes the cookies and headers it needs.
  default_cache_behavior {
    target_origin_id           = local.origin_id
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name = "cerberus-console-session"
  }

  # The origin must be reachable by the service SG before CloudFront routes.
  depends_on = [aws_vpc_security_group_ingress_rule.from_cloudfront]
}

# --- 4. The Cognito app client ------------------------------------------------
# One per session (ADR 0024 L113). Confidential, code flow (Grafana adds
# PKCE). Created after the distribution because the callback URL holds its
# domain; the instance polls for it at boot (plan option 4.2 A), so nothing
# here depends on the instance and there is no cycle.
resource "aws_cognito_user_pool_client" "grafana" {
  name         = local.name
  user_pool_id = local.standing.console_user_pool_id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [local.callback_url]
  logout_urls                          = [local.logout_url]

  access_token_validity  = local.token_minutes
  id_token_validity      = local.token_minutes
  refresh_token_validity = local.refresh_token_minutes
  auth_session_validity  = 3

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "minutes"
  }

  enable_token_revocation       = true
  prevent_user_existence_errors = "ENABLED"

  # Same minimum surface as the SPA client in modules/console_edge. If the
  # hosted UI refuses to sign in with this set, add ALLOW_USER_SRP_AUTH.
  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]
}
