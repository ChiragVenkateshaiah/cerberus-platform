# Schema registration for 1.7's transform output (since 8.5, gold's
# payments_current and the two bronze tables; silver is Iceberg-owned, see
# below). Columns are declared
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
# Silver's payments_events is no longer declared here (8.5, ADR 0017). It
# became an Apache Iceberg table that the silver Spark job creates and
# commits to through Iceberg's Glue catalog: the table's schema, partition
# spec and current metadata pointer belong to Iceberg, and a Terraform-owned
# definition would fight every commit. Removing this resource is also how
# the Hive table is retired: the apply that removes it deletes only the
# Glue entry (the Hive Parquet under s3://<silver>/payments/ stays), and the
# next exercise's job recreates payments_events as Iceberg under
# s3://<silver>/iceberg/ by a full rebuild from bronze.

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

# --- 8.4: bronze tables for the data-quality suite --------------------------
# Read-only views over bronze so the suite (observability/scale/data_quality.py)
# can reconcile bronze -> silver in Athena, with no cluster. Neither table has
# partitions: Athena reads every object under the location, including the
# dt=/run_id= subdirectories, and the checks take dt and run_id from the
# "$path" pseudo-column -- so there is nothing to register after each run.
# Athena skips objects whose names start with _ or ., which covers Spark's
# _SUCCESS marker and .spark-staging directories.

# The ingestion Lambda's files: one JSON array per file, on a single line
# (payments_lib.upload_day, json.dumps). No JSON SerDe maps a root array to
# rows, so each file is read as one text line and the checks unpack it with
# json_parse. LazySimpleSerDe splits on \001 by default, which never occurs
# in this JSON, so the whole line lands in `line`.
resource "aws_glue_catalog_table" "bronze_payments_raw" {
  name          = "bronze_payments_raw"
  database_name = aws_glue_catalog_database.this.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "text"
  }

  storage_descriptor {
    location      = "s3://${var.bronze_bucket_name}/payments/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe"
    }

    columns {
      name = "line"
      type = "string"
    }
  }
}

# The bulk generator's files: JSON Lines with ADR 0003's nested event shape
# (ADR 0018).
resource "aws_glue_catalog_table" "bronze_payments_bulk" {
  name          = "bronze_payments_bulk"
  database_name = aws_glue_catalog_database.this.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "json"
  }

  storage_descriptor {
    location      = "s3://${var.bronze_bucket_name}/payments_bulk/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "transaction_id"
      type = "string"
    }
    columns {
      name = "event_type"
      type = "string"
    }
    columns {
      name = "event_timestamp"
      type = "string"
    }
    columns {
      name = "amount"
      type = "double"
    }
    columns {
      name = "currency"
      type = "string"
    }
    columns {
      name = "merchant"
      type = "struct<merchant_id:string,name:string,category:string>"
    }
    columns {
      name = "customer"
      type = "struct<customer_id:string,name:string,email:string>"
    }
    columns {
      name = "payment_method"
      type = "struct<type:string,brand:string,last4:string,token:string>"
    }
  }
}

# 8.6: the same files, one run at a time. Partition projection with both keys
# "injected" means Athena builds the S3 path from the query's own
# `run_id = '...' AND dt = '...'` and reads only that directory -- and
# refuses a query without both, so the expensive whole-prefix scan can't
# happen here by accident. Nothing to register after a run. The suite checks
# each new run here, one dt per query; bronze_payments_bulk above stays for
# the --full audit. Only the key columns: the JSON SerDe ignores the rest,
# and Athena reads whole JSON files either way.
resource "aws_glue_catalog_table" "bronze_payments_bulk_by_run" {
  name          = "bronze_payments_bulk_by_run"
  database_name = aws_glue_catalog_database.this.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification              = "json"
    "projection.enabled"        = "true"
    "projection.run_id.type"    = "injected"
    "projection.dt.type"        = "injected"
    "storage.location.template" = "s3://${var.bronze_bucket_name}/payments_bulk/run_id=$${run_id}/dt=$${dt}/"
  }

  partition_keys {
    name = "run_id"
    type = "string"
  }
  partition_keys {
    name = "dt"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.bronze_bucket_name}/payments_bulk/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "transaction_id"
      type = "string"
    }
    columns {
      name = "event_type"
      type = "string"
    }
  }
}
