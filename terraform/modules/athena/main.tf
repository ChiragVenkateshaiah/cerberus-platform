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

  # Workgroup query-execution history isn't real data (it's re-derivable
  # from re-running queries), so unlike the S3 buckets there's no reason to
  # require it be emptied by hand before a destroy.
  force_destroy = true

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

# 8.6: the data-quality suite's own workgroup. At 10M events bronze is
# 4.36 GB, and the suite's full-bronze checks (counts, keys, bulk
# duplicates and manifests) passed the then 1 GiB cutoff above -- five
# checks CANCELLED on exercise-20261009T074853Z, so the fail-closed suite
# failed with nothing wrong in the data. A separate workgroup lifted the
# cutoff for the suite only. (The next run's dbt merge passed 1 GiB too, so
# the shared cutoff is now 10 GiB as well; the suite keeps its own,
# enforced workgroup so its scans stay separate from dbt and serving.) Enforced,
# unlike the shared one: the suite is plain boto3 with no dbt-athena
# external_location problem, so the cutoff can't be overridden per query.
# The full-bronze scans themselves are the 100M problem (about 45 GB of
# bronze, over $1 a run): 8.9 needs cheaper bronze checks, not a bigger
# cutoff.
resource "aws_athena_workgroup" "data_quality" {
  name          = "cerberus_platform_dq"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = var.dq_bytes_scanned_cutoff_bytes
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.results.bucket}/data_quality/"
    }
  }
}
