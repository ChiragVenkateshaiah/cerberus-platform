# 4.2 -- ECR + Fargate compute for the two "CLI-heavy" orchestration steps
# (Spark-on-EKS submission/polling, dbt run) that have no native Step
# Functions integration, per ADR 0009's own conceded friction point. Both
# task definitions point at one shared image (orchestration/runner/) with
# a different CMD baking in which entrypoint script runs -- kept as two
# task defs, not one with a runtime Overrides.command, so each keeps its
# own IAM task role and CloudWatch log group without the state machine
# having to inject anything at invoke time. No aws_ecs_service anywhere
# here -- the state machine's ecs:runTask.sync integration runs each task
# directly, standalone, the same "workload action, not standing
# infrastructure" distinction spark_job's own header draws for
# SparkApplication submissions.

resource "aws_ecr_repository" "runner" {
  name                 = "cerberus-orchestration-runner"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

locals {
  image_uri = "${aws_ecr_repository.runner.repository_url}:latest"
}

# Local build+push, not a CI/CD pipeline -- same "the right amount of
# infrastructure for this phase" call lambda_ingestion's null_resource
# layer build already made (Phase 5 is where a real pipeline arrives).
# Build context is the repo root (../../../..), not this module's
# directory -- the Dockerfile COPYs transform/dbt/ and transform/spark/
# alongside orchestration/runner/ itself.
resource "null_resource" "build_and_push" {
  triggers = {
    dockerfile_hash   = filemd5("${path.module}/../../../orchestration/runner/Dockerfile")
    dockerignore_hash = filemd5("${path.module}/../../../.dockerignore")
    entrypoints_hash = join(",", [
      filemd5("${path.module}/../../../orchestration/runner/entrypoint_transform.sh"),
      filemd5("${path.module}/../../../orchestration/runner/entrypoint_dbt.sh"),
      filemd5("${path.module}/../../../orchestration/runner/lib.sh"),
    ])
    dbt_project_hash = join(",", [
      filemd5("${path.module}/../../../transform/dbt/dbt_project.yml"),
      filemd5("${path.module}/../../../transform/dbt/profiles.yml"),
    ])
    spark_files_hash = join(",", [
      filemd5("${path.module}/../../../transform/spark/spark-application.yaml"),
      filemd5("${path.module}/../../../transform/spark/promote_payments_spark.py"),
    ])
  }

  provisioner "local-exec" {
    # local-exec defaults to /bin/sh, which on this system is dash --
    # dash doesn't support `set -o pipefail` (bash-only), and the first
    # line of this command needs it (aws ecr get-login-password | docker
    # login -- without pipefail, a failure in get-login-password wouldn't
    # necessarily fail the pipeline, since sh takes the last command's
    # exit code). Confirmed live 2026-08-19/20: /bin/sh: set: Illegal
    # option -o pipefail. Explicit interpreter, not a rewrite avoiding
    # pipefail, since the safety property is worth keeping.
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      aws ecr get-login-password --region ${var.region} --profile cerberus-admin \
        | docker login --username AWS --password-stdin ${aws_ecr_repository.runner.repository_url}
      docker build -f ${path.module}/../../../orchestration/runner/Dockerfile \
        -t ${local.image_uri} ${path.module}/../../../
      docker push ${local.image_uri}
    EOT
  }

  depends_on = [aws_ecr_repository.runner]
}

resource "aws_ecs_cluster" "this" {
  name = "cerberus-orchestration"
  # No default_capacity_provider_strategy -- FARGATE is requested per-task
  # (RunTask's LaunchType), not cluster-wide capacity this project would
  # pay to keep warm.
}

resource "aws_cloudwatch_log_group" "transform" {
  name              = "/ecs/cerberus-orchestration-transform"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "dbt" {
  name              = "/ecs/cerberus-orchestration-dbt"
  retention_in_days = 14
}

resource "aws_security_group" "runner" {
  name = "cerberus-orchestration-runner"
  # No apostrophe in this description -- confirmed live 2026-08-19 that
  # AWS's allowed character set for EC2 security group descriptions
  # (a-zA-Z0-9. _-:/()#,@[]+=&;{}!$*) excludes it; "runner's" here caused
  # a real InvalidParameterValue apply failure.
  description = "Egress-only SG for the orchestration runner Fargate tasks -- nothing calls these tasks, they only call out (ECR, S3, Athena, the EKS API, CloudWatch Logs) through the existing single NAT Gateway (ADR 0007)."
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "transform" {
  family                   = "cerberus-orchestration-transform"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.transform_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "transform"
      image     = local.image_uri
      command   = ["/opt/runner/entrypoint_transform.sh"]
      essential = true

      environment = [
        { name = "CLUSTER_NAME", value = var.cluster_name },
        { name = "AWS_REGION", value = var.region },
        { name = "SILVER_BUCKET", value = var.silver_bucket_name },
        { name = "GLUE_DATABASE", value = var.glue_database_name },
        { name = "ATHENA_WORKGROUP", value = var.athena_workgroup_name },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.transform.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "transform"
        }
      }
    }
  ])

  depends_on = [null_resource.build_and_push]
}

resource "aws_ecs_task_definition" "dbt" {
  family                   = "cerberus-orchestration-dbt"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.dbt_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "dbt"
      image     = local.image_uri
      command   = ["/opt/runner/entrypoint_dbt.sh"]
      essential = true

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.dbt.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "dbt"
        }
      }
    }
  ])

  depends_on = [null_resource.build_and_push]
}
