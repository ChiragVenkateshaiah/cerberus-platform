# Medallion bucket topology per ADR 0002: three buckets, one per layer,
# same cerberus-platform-<layer>-<account-id> naming pattern. Bronze already
# exists (hand-created in Phase 0) and is adopted here via `terraform import`
# rather than recreated; silver and gold are new.

locals {
  layers = {
    bronze = {
      bucket_name      = "cerberus-platform-bronze-${var.account_id}"
      phase            = "0"
      enable_lifecycle = true
    }
    silver = {
      bucket_name      = "cerberus-platform-silver-${var.account_id}"
      phase            = "1"
      enable_lifecycle = false
    }
    gold = {
      bucket_name      = "cerberus-platform-gold-${var.account_id}"
      phase            = "1"
      enable_lifecycle = false
    }
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.layers

  bucket = each.value.bucket_name

  tags = {
    Layer = each.key
    Phase = each.value.phase
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.layers

  bucket = aws_s3_bucket.this[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = local.layers

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = local.layers

  bucket = aws_s3_bucket.this[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = local.layers

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Bronze only: 30-day (default) transition to Standard-IA. Not a
# retention/expiration policy -- bronze stays append-only and immutable
# per ADR 0002, this only ages storage class down.
resource "aws_s3_bucket_lifecycle_configuration" "bronze" {
  for_each = { for k, v in local.layers : k => v if v.enable_lifecycle }

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"

    filter {}

    transition {
      days          = var.bronze_ia_transition_days
      storage_class = "STANDARD_IA"
    }
  }
}
