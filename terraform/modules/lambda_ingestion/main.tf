# 2.1/2.2 -- the ingestion Lambda (ADR 0005: pull-shaped, not
# S3-event-triggered -- generate_payments.py produces its own data,
# there's no upstream write to react to). The generation logic itself
# lives in ingestion/scripts/payments_lib.py, shared with the CLI script
# (generate_payments.py) for manual runs -- see
# ingestion/lambda/handler.py's docstring for the full picture.
#
# This module no longer owns the schedule that triggers it -- 4.3 moved
# aws_scheduler_schedule.daily and its own execution role to
# terraform/modules/step_functions (via `moved` blocks in
# terraform/envs/dev/main.tf), retargeted to start the orchestration state
# machine instead of invoking this Lambda directly, per ADR 0009. This
# Lambda is still directly invocable by hand (as before 2.1) and is what
# the state machine's own InvokeIngestion step calls -- it just isn't
# independently scheduled anymore.

# --- Function code: handler.py + payments_lib.py, flattened into one zip
# so they import as siblings, same as they will when the Lambda unzips
# them at /var/task.

data "archive_file" "function" {
  type        = "zip"
  output_path = "${path.module}/build/ingest_payments.zip"

  source {
    content  = file("${path.module}/../../../ingestion/lambda/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../../../ingestion/scripts/payments_lib.py")
    filename = "payments_lib.py"
  }
}

# --- Faker layer: pip-installed at apply time, not committed as a binary.
# boto3/botocore are excluded from ../../../ingestion/lambda/requirements.txt
# on purpose -- the Lambda runtime ships both already. This is the one
# place this project's Terraform shells out (local-exec) rather than
# staying pure IaC; there's no dependency-bundling primitive in the AWS
# provider itself, and a full CI/CD build pipeline is Phase 5's job, not
# this one's.

resource "null_resource" "build_layer" {
  triggers = {
    requirements_hash = filemd5("${path.module}/../../../ingestion/lambda/requirements.txt")
  }

  provisioner "local-exec" {
    command = "${path.module}/../../../.venv/bin/pip install -r ${path.module}/../../../ingestion/lambda/requirements.txt -t ${path.module}/build/layer/python --no-cache-dir --quiet"
  }
}

data "archive_file" "faker_layer" {
  type        = "zip"
  source_dir  = "${path.module}/build/layer"
  output_path = "${path.module}/build/faker_layer.zip"

  depends_on = [null_resource.build_layer]
}

resource "aws_lambda_layer_version" "faker" {
  layer_name          = "cerberus-ingestion-faker"
  filename            = data.archive_file.faker_layer.output_path
  source_code_hash    = data.archive_file.faker_layer.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

# --- The function itself ---------------------------------------------

resource "aws_lambda_function" "ingest_payments" {
  function_name = "cerberus-ingest-payments"
  role          = var.execution_role_arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  filename         = data.archive_file.function.output_path
  source_code_hash = data.archive_file.function.output_base64sha256

  layers = [aws_lambda_layer_version.faker.arn]

  environment {
    variables = {
      BRONZE_BUCKET      = var.bronze_bucket_name
      RETIRE_ON_OR_AFTER = var.retire_on_or_after
      TRANSACTION_COUNT  = tostring(var.transaction_count)
    }
  }
}
