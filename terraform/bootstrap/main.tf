# Terraform state backend, hand-created in Phase 0 (0.5) and adopted here
# via `terraform import` rather than recreated -- same adoption pattern
# 1.4 used for the bronze bucket.

resource "aws_s3_bucket" "tfstate" {
  bucket = "cerberus-platform-tfstate-131715059025"

  tags = {
    Purpose = "terraform-state"
    Phase   = "0"
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# State lock table. `dynamodb_table` (envs/dev/versions.tf's backend block)
# is deprecated in favor of the S3 backend's native `use_lockfile` locking,
# but this table is kept deliberately -- already built, effectively free
# on-demand billing, revisit only after the MVP (Phase 1) is done.
resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "cerberus-platform-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Purpose = "terraform-lock"
    Phase   = "0"
  }
}
