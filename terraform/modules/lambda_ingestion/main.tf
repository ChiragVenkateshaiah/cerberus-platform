# 2.1/2.2 -- the ingestion Lambda and its EventBridge Scheduler trigger
# (ADR 0005: pull-shaped, not S3-event-triggered -- generate_payments.py
# produces its own data, there's no upstream write to react to). Replaces
# cerberus-payments.timer + run_payments_scheduled.sh's trigger role (2.5
# retires that timer once this is verified end to end). The generation
# logic itself lives in ingestion/scripts/payments_lib.py, shared with the
# CLI script (generate_payments.py) for manual runs -- see
# ingestion/lambda/handler.py's docstring for the full picture.

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

# --- EventBridge Scheduler: daily invocation, no invocation-level retry --
# (ADR 0005: retries here would regenerate a different, unseeded dataset
# and duplicate data into append-only bronze -- payments_lib.upload_day's
# per-partition retry is the only retry layer). Scheduler needs its own
# execution role distinct from the Lambda's -- this is the role Scheduler
# itself assumes to call lambda:InvokeFunction, not the role the function
# runs as.

resource "aws_iam_role" "scheduler" {
  name = "cerberus-ingest-payments-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "scheduler.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "invoke-ingest-payments"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.ingest_payments.arn
      }
    ]
  })
}

resource "aws_scheduler_schedule" "daily" {
  name       = "cerberus-ingest-payments-daily"
  group_name = "default"

  # UTC, fixed explicitly rather than left to default: generate_payments.py
  # (and this handler) partition events by UTC event day, so an
  # unconsidered timezone choice here would silently shift which dt=
  # partition a run lands in relative to today's systemd timer
  # (OnCalendar=daily, local time) -- ADR 0005.
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.ingest_payments.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
