# Schema registration for 1.7's transform output. Columns are declared
# explicitly here rather than discovered by a Glue Crawler -- the schema
# is already fully known and controlled (transform/scripts/promote_payments.py
# writes it), so a Crawler would just be paying to re-derive something
# already certain. Partitions on payments_events are NOT managed here --
# they're data, not infrastructure, and grow every time the transform
# runs; promote_payments.py registers them directly via the Glue API
# (glue:BatchCreatePartition, granted to cerberus-transform in the iam
# module) using this same column list, kept in sync by hand since Terraform
# and that Python script don't share a schema source today.

resource "aws_glue_catalog_database" "this" {
  name = "cerberus_platform"
}

locals {
  payment_columns = [
    { name = "transaction_id", type = "string" },
    { name = "event_type", type = "string" },
    { name = "event_timestamp", type = "timestamp" },
    { name = "amount", type = "double" },
    { name = "currency", type = "string" },
    { name = "merchant_id", type = "string" },
    { name = "merchant_name", type = "string" },
    { name = "merchant_category", type = "string" },
    { name = "customer_id", type = "string" },
    { name = "customer_name", type = "string" },
    { name = "customer_email", type = "string" },
    { name = "payment_method_type", type = "string" },
    { name = "payment_method_brand", type = "string" },
    { name = "payment_method_last4", type = "string" },
    { name = "payment_method_token", type = "string" },
  ]
}

# Silver: full event history, dt=YYYY-MM-DD partitioned.
resource "aws_glue_catalog_table" "payments_events" {
  name          = "payments_events"
  database_name = aws_glue_catalog_database.this.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification  = "parquet"
    compressionType = "snappy"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.silver_bucket_name}/payments/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.payment_columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}

# Gold: current-state, one row per transaction_id, unpartitioned.
resource "aws_glue_catalog_table" "payments_current" {
  name          = "payments_current"
  database_name = aws_glue_catalog_database.this.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification  = "parquet"
    compressionType = "snappy"
  }

  storage_descriptor {
    location      = "s3://${var.gold_bucket_name}/payments_current/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.payment_columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}
