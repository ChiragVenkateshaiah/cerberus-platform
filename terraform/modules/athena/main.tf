# Minimal Athena plumbing, pulled forward from 1.10 into 1.9 -- dbt's
# Athena adapter can't run at all without a query-results location and a
# workgroup, so this exists as 1.9's prerequisite rather than getting built
# twice. 1.10 reuses this module's outputs for cerberus-serving's own
# query-execution permissions; it does not need its own results
# bucket/workgroup.

resource "aws_s3_bucket" "results" {
  bucket = "cerberus-platform-athena-results-${var.account_id}"

  tags = {
    Purpose = "athena-query-results"
    Phase   = "1"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "results" {
  bucket = aws_s3_bucket.results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Query results are transient re-derivable output, not data -- expire
# rather than transition to IA (unlike bronze, which keeps its objects
# indefinitely per ADR 0002).
resource "aws_s3_bucket_lifecycle_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    id     = "expire-query-results"
    status = "Enabled"

    filter {}

    expiration {
      days = var.results_expiration_days
    }
  }
}

resource "aws_athena_workgroup" "this" {
  name = "cerberus_platform"

  # enforce_workgroup_configuration is deliberately false: dbt-athena skips
  # setting a Hive table's external_location in its CREATE TABLE statement
  # whenever the workgroup enforces its own output location (to avoid the
  # two conflicting), which would silently strand every dbt-managed table
  # under this workgroup's results-bucket default instead of the gold
  # bucket. With enforcement off, callers that don't override result
  # config (dbt included) still get this workgroup's output_location and
  # bytes_scanned_cutoff_per_query as defaults -- only the ability to
  # override them is what's given up.
  configuration {
    enforce_workgroup_configuration    = false
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff_bytes
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.results.bucket}/"
    }
  }
}
