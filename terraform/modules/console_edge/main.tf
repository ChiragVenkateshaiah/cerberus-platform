# 9.2 (Phase 9 -- the demo console), step 7: the standing edge. S3 site
# bucket -> CloudFront (OAC) with /api/* to an HTTP API with a Cognito JWT
# authorizer -> the command Lambda. See docs/adr/0024-demo-console.md, and
# its Amendment (2026-11-02), which replaces rule 8's reserved concurrency
# with stage throttling and moves sign-in to the classic hosted UI
# (managed_login_version = 1) until the AWS provider is on 6.x.
#
# Instantiated from envs/dev-standing: every piece here (S3, CloudFront, an
# HTTP API, Cognito under 10,000 MAU, Lambda) has no fixed fee, so the
# idle cost is $0 -- the same placement reasoning as the lineage module.
# Names are fixed by docs/plans/2026-10-27-console-iam-prerequisites.md:
# cerberus-platform-console-<account>, cerberus-console-*, and the
# /aws/lambda/cerberus-console-* and /aws/apigateway/cerberus-console-*
# log groups.
#
# The Cognito user pool has deletion_protection = ACTIVE, so the invited
# users made by hand are never lost to a forced replacement. The side
# effect: `make standing-destroy` fails on the pool until the protection is
# set to INACTIVE and applied first.
#
# The execution role (cerberus-console-cli) lives in console_roles. This
# module only adds its CloudWatch Logs write, as a separate inline policy.

locals {
  bucket_name = "cerberus-platform-console-${var.account_id}"
  function    = "cerberus-console-command"
  api_name    = "cerberus-console-api"
  cognito_url = "https://${var.cognito_domain_prefix}.auth.${var.region}.amazoncognito.com"

  # Built from the distribution domain, which the client needs and the
  # distribution does not (the CSP uses the prefix string), so no cycle.
  callback_url = "https://${aws_cloudfront_distribution.this.domain_name}/terminal/index.html"
  logout_url   = "https://${aws_cloudfront_distribution.this.domain_name}/"
  # 9.5 (ADR 0024 amendment 2026-11-12): the terminal ends a session with
  # Cognito /logout and returns to its own page, so that URL is registered too.
  logout_terminal_url = "https://${aws_cloudfront_distribution.this.domain_name}/terminal/index.html"

  repo_root     = "${path.module}/../../.."
  package_files = fileset("${local.repo_root}/console/cerberus_console", "*.py")
  run_files     = fileset("${local.repo_root}/observability/scale/runs", "*.json")
}

# --- 1. Site bucket -------------------------------------------------------
# Private; only the CloudFront distribution may read it (OAC). No
# versioning: 9.4's publish rebuilds the contents. Terraform manages one
# object, healthz.txt, the probe for the OAC check. 9.4 owns index.html and
# the rest.

resource "aws_s3_bucket" "site" {
  bucket        = local.bucket_name
  force_destroy = true

  tags = {
    Phase     = "9"
    Component = "console"
  }
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id

  # The public access block is created first: it rejects a public policy,
  # and applying both at once can race.
  depends_on = [aws_s3_bucket_public_access_block.site]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/*"
        Condition = {
          StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.this.arn }
        }
      },
      {
        # ADR 0024 step 10: artifacts/ holds the session host's Grafana and
        # plugin packages and the per-session bundle. They are private: the
        # host reads them with its own role, and CloudFront never serves them.
        Sid       = "DenyCloudFrontArtifacts"
        Effect    = "Deny"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/artifacts/*"
      }
    ]
  })
}

resource "aws_s3_object" "healthz" {
  bucket       = aws_s3_bucket.site.id
  key          = "healthz.txt"
  content      = "ok"
  content_type = "text/plain"
}

# --- 2. CloudFront --------------------------------------------------------
# One distribution, one origin per path: S3 for the site, the HTTP API for
# /api/*. The default certificate and no standard logging are known limits
# (a custom certificate costs a domain; standing logs need an ACL-enabled
# bucket) -- both go to 9.7's Well-Architected pass.

# AWS-managed policies, read by name rather than by hard-coded ID.
data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

# Forwards every viewer header (so Authorization reaches the API) except
# Host. AllViewer would send the CloudFront Host, which API Gateway rejects.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "cerberus-console-site"
  description                       = "OAC for the console site bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name = "cerberus-console-security-headers"
  # The terminal keeps this strict CSP (ADR 0024 amendment 2026-11-12); the
  # comment below is an AWS attribute, so it stays as is to avoid an update.
  comment = "Console security headers (ADR 0024). 9.5 may relax style-src for the terminal."

  security_headers_config {
    content_security_policy {
      override = true
      content_security_policy = join("; ", [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self' ${local.cognito_url}",
        "form-action 'self' ${local.cognito_url}",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
        "upgrade-insecure-requests",
      ])
    }

    strict_transport_security {
      override                   = true
      access_control_max_age_sec = 31536000
    }

    content_type_options {
      override = true
    }

    frame_options {
      override     = true
      frame_option = "DENY"
    }

    referrer_policy {
      override        = true
      referrer_policy = "no-referrer"
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      override = true
      value    = "camera=(), microphone=(), geolocation=()"
    }
  }
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  comment             = "cerberus demo console"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  is_ipv6_enabled     = true
  http_version        = "http2and3"

  origin {
    origin_id                = "site"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    origin_id   = "api"
    domain_name = "${aws_apigatewayv2_api.this.id}.execute-api.${var.region}.amazonaws.com"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id           = "site"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# --- 3. Cognito -----------------------------------------------------------
# Invite-only: self sign-up is off and the owner creates users by hand with
# admin-create-user -- never in this repo. Username sign-in, no email or
# phone attributes, so nothing personal is stored. Essentials tier, set
# explicitly, to keep the option of managed login (Lite lacks it); the free
# tier is 10,000 MAU. Classic hosted UI (version 1): AWS provider 5.100 has
# no managed-login branding resource, and version 2 pages do not work
# without a style.

resource "aws_cognito_user_pool" "this" {
  name                = "cerberus-console"
  user_pool_tier      = "ESSENTIALS"
  deletion_protection = "ACTIVE"
  mfa_configuration   = "OFF"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  username_configuration {
    case_sensitive = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }
}

resource "aws_cognito_user_pool_domain" "this" {
  domain                = var.cognito_domain_prefix
  user_pool_id          = aws_cognito_user_pool.this.id
  managed_login_version = 1
}

# Public client (a browser SPA), so no secret. Authorization-code flow;
# the SPA (9.5) always sends a PKCE S256 challenge. Cognito has no switch
# to require PKCE.
resource "aws_cognito_user_pool_client" "spa" {
  name         = "cerberus-console-spa"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [local.callback_url]
  logout_urls                          = [local.logout_url, local.logout_terminal_url]

  access_token_validity  = var.token_validity_minutes
  id_token_validity      = var.token_validity_minutes
  refresh_token_validity = var.token_validity_minutes
  auth_session_validity  = 3

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "minutes"
  }

  enable_token_revocation       = true
  prevent_user_existence_errors = "ENABLED"

  # The minimum surface: no SRP or password API for scripts. If the hosted
  # UI refuses to sign in with this set, add ALLOW_USER_SRP_AUTH.
  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]
}

# --- 4. HTTP API ----------------------------------------------------------
# No CORS: CloudFront serves /api from the same origin. The authorizer
# checks the access token's issuer and audience (an access token carries
# client_id, which API Gateway accepts when aud is absent). Cognito ID
# tokens carry no scope claim, so requiring the openid scope on the route
# refuses them.

resource "aws_apigatewayv2_api" "this" {
  name          = local.api_name
  protocol_type = "HTTP"
  description   = "Demo console command API (9.2) -- POST /api/command"
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.this.id
  name             = "cerberus-console-cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer   = "https://${aws_cognito_user_pool.this.endpoint}"
    audience = [aws_cognito_user_pool_client.spa.id]
  }
}

resource "aws_apigatewayv2_integration" "command" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.command.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "command" {
  api_id               = aws_apigatewayv2_api.this.id
  route_key            = "POST /api/command"
  target               = "integrations/${aws_apigatewayv2_integration.command.id}"
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.jwt.id
  authorization_scopes = ["openid"]
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.api_name}"
  retention_in_days = var.access_log_retention_days
}

# ADR 0024 rule 9: the access log carries the Cognito sub, so every
# command maps to an invited account. A failed JWT check logs authError
# and an empty sub.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttle_rate_limit
    throttling_burst_limit = var.throttle_burst_limit
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    # Behind CloudFront, edgeIp is the edge address, not the visitor. The
    # audit key is sub (ADR 0024 rule 9).
    format = jsonencode({
      requestId          = "$context.requestId"
      requestTime        = "$context.requestTime"
      routeKey           = "$context.routeKey"
      status             = "$context.status"
      authError          = "$context.authorizer.error"
      sub                = "$context.authorizer.claims.sub"
      integrationStatus  = "$context.integrationStatus"
      integrationLatency = "$context.integrationLatency"
      responseLength     = "$context.responseLength"
      edgeIp             = "$context.identity.sourceIp"
    })
  }
}

# --- 5. Command Lambda ----------------------------------------------------
# The console package plus the committed run records, zipped at plan time
# (boto3 comes from the runtime). Dynamic source blocks add each file
# under cerberus_console/ or runs/, so tests/ and __pycache__/ never enter
# the zip.

data "archive_file" "command" {
  type             = "zip"
  output_path      = "${path.module}/build/console_command.zip"
  output_file_mode = "0644"

  dynamic "source" {
    for_each = local.package_files
    content {
      content  = file("${local.repo_root}/console/cerberus_console/${source.value}")
      filename = "cerberus_console/${source.value}"
    }
  }

  dynamic "source" {
    for_each = local.run_files
    content {
      content  = file("${local.repo_root}/observability/scale/runs/${source.value}")
      filename = "runs/${source.value}"
    }
  }

  lifecycle {
    precondition {
      condition     = contains(local.package_files, "api.py")
      error_message = "console/cerberus_console/api.py is missing, so the Lambda package would be empty."
    }
  }
}

resource "aws_cloudwatch_log_group" "command" {
  name              = "/aws/lambda/${local.function}"
  retention_in_days = var.log_retention_days
}

# The role has no CloudWatch Logs write. A separate inline policy, scoped
# to this one log group, keeps this module off console_roles' policy and
# avoids AWSLambdaBasicExecutionRole, which allows CreateLogGroup on *.
resource "aws_iam_role_policy" "console_cli_logs" {
  name = "cerberus-console-cli-logs"
  role = var.console_cli_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteCommandLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.command.arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "command" {
  function_name = local.function
  role          = var.console_cli_role_arn
  handler       = "cerberus_console.api.lambda_handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  filename         = data.archive_file.command.output_path
  source_code_hash = data.archive_file.command.output_base64sha256

  reserved_concurrent_executions = var.command_reserved_concurrency

  environment {
    variables = {
      CERBERUS_RUNS_DIR          = "/var/task/runs"
      CERBERUS_STATE_MACHINE_ARN = var.state_machine_arn
    }
  }

  # The log group and its write grant exist before the first invocation.
  depends_on = [
    aws_cloudwatch_log_group.command,
    aws_iam_role_policy.console_cli_logs,
  ]
}

resource "aws_lambda_permission" "api_invoke" {
  statement_id  = "AllowInvokeFromHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.command.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/POST/api/command"
}
