# 17.3b (ADR 0030 Decisions 2 to 6, 10, 13): the per-session delivery edge.
# Two private S3 buckets, one CloudFront distribution (OAC) where every
# behaviour needs a signed cookie, a key group over one public key, a
# KeyValueStore + viewer-request Function for /license*, and CloudFront
# standard logging v2 to the log bucket.
#
# Instantiated only from envs/dev-launch (human-run, never CI, ADR 0030
# Decision 2). Everything here is named cerberus-launch-* or
# cerberus-platform-launch-<account> to match iam/cerberus-admin/policies/
# cerberus-admin-launch.json. The load generator is in load_gen.tf.
#
# Public keys and key groups cannot be tagged (ADR 0030 Context); the check
# tooling finds them by the cerberus-launch- name prefix.

locals {
  build_bucket_name = "cerberus-platform-launch-build-${var.account_id}"
  logs_bucket_name  = "cerberus-platform-launch-logs-${var.account_id}"
  # One trailing newline always: the session script passes the PEM without it, and a
  # different encoded_key would force a replacement on every apply.
  public_key_pem = "${trimspace(coalesce(var.public_key_pem, file("${path.module}/default_public_key.pem")))}\n"

  tags = {
    Project = "cerberus-platform"
    Stack   = "dev-launch"
  }

  # The explicit allowlist of CDN log fields (ADR 0030 Decision 10). The
  # excluded names are c-ip, x-forwarded-for, c-port, cs(Cookie), cs(Referer)
  # and cs(User-Agent). A test fails if one of them appears in this list.
  # Field names are checked against the AWS CloudFront standard-logs
  # reference. The timestamp field is "timestamp(ms)" in v2; plain "timestamp"
  # is not valid.
  log_fields = [
    "timestamp(ms)",
    "x-edge-request-id",
    "x-edge-location",
    "x-edge-result-type",
    "x-edge-response-result-type",
    "sc-status",
    "sc-bytes",
    "cs-method",
    "cs-uri-stem",
    "time-taken",
    "time-to-first-byte",
    "cs-protocol",
  ]
}

# --- 1. Buckets -------------------------------------------------------------
# force_destroy: stage 2 of the destroy must leave nothing (ADR 0030 Decision 2).
resource "aws_s3_bucket" "build" {
  bucket        = local.build_bucket_name
  force_destroy = true

  tags = merge(local.tags, { Component = "launch-build" })
}

resource "aws_s3_bucket" "logs" {
  bucket        = local.logs_bucket_name
  force_destroy = true

  tags = merge(local.tags, { Component = "launch-logs" })
}

resource "aws_s3_bucket_public_access_block" "build" {
  bucket = aws_s3_bucket.build.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "build" {
  bucket = aws_s3_bucket.build.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "build" {
  bucket = aws_s3_bucket.build.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_policy" "build" {
  bucket = aws_s3_bucket.build.id

  # The public access block first: it rejects a public policy, and applying
  # both at once can race (same as console_edge).
  depends_on = [aws_s3_bucket_public_access_block.build]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # build/ and patch/ only. scenarios/ is the generator's private input
        # and is not readable by CloudFront.
        Sid       = "AllowCloudFrontReadChunks"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource = [
          "${aws_s3_bucket.build.arn}/build/*",
          "${aws_s3_bucket.build.arn}/patch/*",
        ]
        Condition = {
          StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.this.arn }
        }
      }
    ]
  })
}

# The policy is ours, with the prefix, source account and source ARN, so that
# AWS does not append a statement of its own when the delivery is created.
resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id

  depends_on = [aws_s3_bucket_public_access_block.logs]

  # The AWS cross-account example policy adds the condition "s3:x-amz-acl" =
  # "bucket-owner-full-control". This policy is the same-account form without
  # it. The ACL condition, and JSON output for S3 delivery, are unverified
  # until the 17.6 smoke (README).
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowLogDeliveryWrite"
        Effect    = "Allow"
        Principal = { Service = "delivery.logs.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.logs.arn}/cdn/*"
        Condition = {
          StringEquals = { "aws:SourceAccount" = var.account_id }
          ArnLike      = { "aws:SourceArn" = "arn:aws:logs:${var.region}:${var.account_id}:delivery-source:cerberus-launch-*" }
        }
      }
    ]
  })
}

# --- 2. Signing key and key group ------------------------------------------
# name_prefix + create_before_destroy: the key group references the key, so a
# fixed name would collide when the key is replaced (ADR 0030 Decision 4).
resource "aws_cloudfront_public_key" "this" {
  name_prefix = "cerberus-launch-"
  comment     = "cerberus launch edge signing key"
  encoded_key = local.public_key_pem

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudfront_key_group" "this" {
  name    = "cerberus-launch-keys"
  comment = "cerberus launch edge"
  items   = [aws_cloudfront_public_key.this.id]
}

# --- 3. KeyValueStore and the /license* Function ----------------------------
resource "aws_cloudfront_key_value_store" "release" {
  name    = "cerberus-launch-release"
  comment = "release_at, epoch seconds, written by Terraform"
}

resource "aws_cloudfrontkeyvaluestore_key" "release_at" {
  key_value_store_arn = aws_cloudfront_key_value_store.release.arn
  key                 = "release_at"
  value               = tostring(var.release_at_epoch)
}

resource "aws_cloudfront_function" "license" {
  name    = "cerberus-launch-license"
  runtime = "cloudfront-js-2.0"
  comment = "403 before release_at, 200 after; fails closed"
  publish = true
  code    = file("${path.module}/function/license.js")

  key_value_store_associations = [aws_cloudfront_key_value_store.release.arn]
}

# --- 4. CloudFront ----------------------------------------------------------
data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

resource "aws_cloudfront_origin_access_control" "build" {
  name                              = "cerberus-launch-oac"
  description                       = "OAC for the launch build bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Chunks are content-addressed and immutable: one year, and nothing in the
# cache key (no query string, cookie or header). No compression, so the bytes
# served equal the bytes stored.
resource "aws_cloudfront_cache_policy" "chunks" {
  name        = "cerberus-launch-chunks"
  comment     = "immutable content-addressed chunks"
  min_ttl     = 31536000
  default_ttl = 31536000
  max_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = false
    enable_accept_encoding_brotli = false

    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  comment         = "cerberus launch edge"
  price_class     = "PriceClass_200"
  is_ipv6_enabled = true
  http_version    = "http2and3"

  # No Origin Shield: AWS does not allow load tests on it (ADR 0030).
  origin {
    origin_id                = "build"
    domain_name              = aws_s3_bucket.build.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.build.id
  }

  # Everything is signed, so there is no unsigned path. The default behaviour
  # caches nothing.
  default_cache_behavior {
    target_origin_id       = "build"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = false
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_disabled.id
    trusted_key_groups     = [aws_cloudfront_key_group.this.id]
  }

  ordered_cache_behavior {
    path_pattern           = "/build/*"
    target_origin_id       = "build"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = false
    cache_policy_id        = aws_cloudfront_cache_policy.chunks.id
    trusted_key_groups     = [aws_cloudfront_key_group.this.id]
  }

  ordered_cache_behavior {
    path_pattern           = "/patch/*"
    target_origin_id       = "build"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = false
    cache_policy_id        = aws_cloudfront_cache_policy.chunks.id
    trusted_key_groups     = [aws_cloudfront_key_group.this.id]
  }

  # The Function answers every request; the S3 origin is only there to make
  # the behaviour valid.
  ordered_cache_behavior {
    path_pattern           = "/license*"
    target_origin_id       = "build"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = false
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_disabled.id
    trusted_key_groups     = [aws_cloudfront_key_group.this.id]

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.license.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # The default certificate. Its minimum TLS version cannot be raised without
  # a custom domain and certificate (README).
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# --- 5. Standard logging v2 -------------------------------------------------
# All in us-east-1. The destination prefix is cdn. suffix_path sets the rest of
# the key to <DistributionId>/<yyyy>/<MM>/<dd>/<HH>: no account ID and no hive
# paths (enable_hive_compatible_path stays off). collect.sh still refuses a
# path with an account ID.
resource "aws_cloudwatch_log_delivery_source" "cdn" {
  name         = "cerberus-launch-cdn"
  log_type     = "ACCESS_LOGS"
  resource_arn = aws_cloudfront_distribution.this.arn
}

resource "aws_cloudwatch_log_delivery_destination" "cdn" {
  name          = "cerberus-launch-cdn"
  output_format = "json"

  delivery_destination_configuration {
    destination_resource_arn = "${aws_s3_bucket.logs.arn}/cdn"
  }
}

resource "aws_cloudwatch_log_delivery" "cdn" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.cdn.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.cdn.arn
  record_fields            = local.log_fields

  s3_delivery_configuration {
    suffix_path = "{DistributionId}/{yyyy}/{MM}/{dd}/{HH}"
  }

  depends_on = [aws_s3_bucket_policy.logs]
}
