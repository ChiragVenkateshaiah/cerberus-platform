# 6.4b (Phase 6 -- lineage). A serverless OpenLineage event collector:
# API Gateway HTTP API -> Lambda -> S3. See
# docs/adr/0013-lineage-openlineage-serverless-collector.md for why this
# shape and not Marquez (a standing Postgres + web service) or Amazon
# DataZone (a managed domain) -- both are idle infrastructure with a
# monthly cost, exactly what ADR 0007/0009/0011 spent three phases keeping
# out of this platform.
#
# Instantiated from envs/dev-standing: every piece here (HTTP API, Lambda,
# S3) is zero-idle-cost, the same placement reasoning as the orchestration
# and observability modules.
#
# 6.4c wires the producers (openlineage-spark on the EKS job,
# openlineage-dbt on the Fargate dbt task) to POST here. 6.4d reads the
# accumulated events back out of S3 and renders the graph onto the Pages
# site alongside the dbt docs.

locals {
  name        = "cerberus-lineage-collector"
  bucket_name = "cerberus-platform-lineage-${var.account_id}"
}

# --- 1. Event store -------------------------------------------------------
# Write-once, immutable event files, each under a unique key (epoch-ms +
# runId + uuid -- see the handler). Versioning is deliberately NOT enabled:
# no key is ever overwritten, so it would only ever add noise and cost.
# Lifecycle expiry keeps the prefix bounded.

resource "aws_s3_bucket" "lineage" {
  bucket = local.bucket_name

  tags = {
    Phase     = "6"
    Component = "lineage"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lineage" {
  bucket = aws_s3_bucket.lineage.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "lineage" {
  bucket = aws_s3_bucket.lineage.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "lineage" {
  bucket = aws_s3_bucket.lineage.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "lineage" {
  bucket = aws_s3_bucket.lineage.id

  rule {
    id     = "expire-events"
    status = "Enabled"

    filter {
      prefix = "events/"
    }

    expiration {
      days = var.event_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# --- 2. Collector Lambda ------------------------------------------------
# boto3-only (like the freshness probe) -- a plain archive_file over one
# committed handler, no null_resource/pip layer step.

data "archive_file" "collector" {
  type        = "zip"
  output_path = "${path.module}/build/lineage_collector.zip"

  source {
    content  = file("${path.module}/../../../lineage/collector/handler.py")
    filename = "handler.py"
  }
}

resource "aws_iam_role" "collector" {
  name = local.name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

# CloudWatch Logs boilerplate -- the same AWS-managed-policy exception
# terraform/modules/iam and terraform/modules/observability already make.
resource "aws_iam_role_policy_attachment" "collector_logs" {
  role       = aws_iam_role.collector.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "collector" {
  name = "${local.name}-policy"
  role = aws_iam_role.collector.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Write-only, and only under events/. The collector never reads
        # back what it wrote -- that is 6.4d's job, with its own identity.
        Sid      = "WriteLineageEvents"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.lineage.arn}/events/*"
      }
    ]
  })
}

resource "aws_lambda_function" "collector" {
  function_name = local.name
  role          = aws_iam_role.collector.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = var.collector_timeout_seconds
  memory_size   = 128

  filename         = data.archive_file.collector.output_path
  source_code_hash = data.archive_file.collector.output_base64sha256

  environment {
    variables = {
      LINEAGE_BUCKET = aws_s3_bucket.lineage.id
    }
  }
}

resource "aws_cloudwatch_log_group" "collector" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = var.log_retention_days
}

# --- 3. HTTP API --------------------------------------------------------
# HTTP API (v2), not REST: cheaper ($1.00 vs $3.50 per million), and all
# this needs is one unauthenticated POST route with a Lambda proxy
# integration and a stage-level rate cap. No API keys, no usage plans, no
# request validation -- ADR 0013's "unauthenticated + throttled" decision.

resource "aws_apigatewayv2_api" "collector" {
  name          = local.name
  protocol_type = "HTTP"
  description   = "OpenLineage event collector (6.4b) -- POST /api/v1/lineage"
}

resource "aws_apigatewayv2_integration" "collector" {
  api_id                 = aws_apigatewayv2_api.collector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.collector.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "collector" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "POST /api/v1/lineage"
  target    = "integrations/${aws_apigatewayv2_integration.collector.id}"
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.collector.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttle_rate_limit
    throttling_burst_limit = var.throttle_burst_limit
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      integrationError = "$context.integrationErrorMessage"
      responseLength   = "$context.responseLength"
      sourceIp         = "$context.identity.sourceIp"
    })
  }
}

resource "aws_lambda_permission" "api_invoke" {
  statement_id  = "AllowInvokeFromHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.collector.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}
