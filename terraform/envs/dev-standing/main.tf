# ADR 0011 (5.1): the CI-managed half of what used to be one envs/dev root.
# Holds every resource that costs nothing (or a fixed, always-on amount)
# sitting idle: S3, IAM (minus cerberus-spark), Glue, Athena, the ingestion
# Lambda, the orchestration layer (ECR/ECS task defs/Step Functions), and
# the VPC's free core (subnets/IGW/routing, no NAT). GitHub Actions plans
# every PR against this root and applies it on merge to main.
#
# The spin-up/destroy compute layer (VPC's NAT Gateway, EKS, Spark
# Operator, the Spark job's service account, cerberus-spark) lives in the
# sibling envs/dev-compute root instead, with its own state, applied only
# by a human per exercise -- never by CI. See envs/dev-compute/main.tf's
# header and docs/adr/0011-ci-cd-github-actions-oidc.md for the full
# reasoning behind the split.

locals {
  eks_cluster_name = "cerberus-platform-eks"
}

module "s3_medallion" {
  source = "../../modules/s3_medallion"

  account_id = data.aws_caller_identity.current.account_id
}

module "glue_catalog" {
  source = "../../modules/glue_catalog"

  silver_bucket_name = module.s3_medallion.bucket_names["silver"]
  gold_bucket_name   = module.s3_medallion.bucket_names["gold"]
}

module "athena" {
  source = "../../modules/athena"

  account_id = data.aws_caller_identity.current.account_id
}

module "vpc" {
  source = "../../modules/vpc"
}

module "iam" {
  source = "../../modules/iam"

  bucket_arns           = module.s3_medallion.bucket_arns
  trusted_principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/cerberus-admin"

  account_id                = data.aws_caller_identity.current.account_id
  glue_database_name        = module.glue_catalog.database_name
  glue_table_names          = values(module.glue_catalog.table_names)
  glue_partition_table_name = module.glue_catalog.table_names["payments_events"]

  athena_workgroup_name     = module.athena.workgroup_name
  athena_results_bucket_arn = module.athena.results_bucket_arn

  eks_cluster_name = local.eks_cluster_name
}

module "lambda_ingestion" {
  source = "../../modules/lambda_ingestion"

  bronze_bucket_name = module.s3_medallion.bucket_names["bronze"]
  execution_role_arn = module.iam.ingestion_lambda_role_arn
}

module "orchestration_runner" {
  source = "../../modules/orchestration_runner"

  account_id         = data.aws_caller_identity.current.account_id
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  transform_task_role_arn = module.iam.orchestration_transform_role_arn
  dbt_task_role_arn       = module.iam.orchestration_dbt_role_arn
  task_execution_role_arn = module.iam.orchestration_ecs_execution_role_arn

  silver_bucket_name    = module.s3_medallion.bucket_names["silver"]
  cluster_name          = local.eks_cluster_name
  glue_database_name    = module.glue_catalog.database_name
  athena_workgroup_name = module.athena.workgroup_name
}

module "step_functions" {
  source = "../../modules/step_functions"

  account_id = data.aws_caller_identity.current.account_id

  state_machine_role_arn  = module.iam.orchestration_state_machine_role_arn
  state_machine_role_name = module.iam.orchestration_state_machine_role_name

  ingestion_lambda_arn          = module.lambda_ingestion.function_arn
  ecs_cluster_arn               = module.orchestration_runner.cluster_arn
  transform_task_definition_arn = module.orchestration_runner.transform_task_definition_arn
  dbt_task_definition_arn       = module.orchestration_runner.dbt_task_definition_arn
  transform_task_role_arn       = module.iam.orchestration_transform_role_arn
  dbt_task_role_arn             = module.iam.orchestration_dbt_role_arn
  task_execution_role_arn       = module.iam.orchestration_ecs_execution_role_arn

  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_id  = module.orchestration_runner.security_group_id

  athena_workgroup_name     = module.athena.workgroup_name
  athena_database_name      = module.glue_catalog.database_name
  athena_results_bucket_arn = module.athena.results_bucket_arn
  gold_bucket_arn           = module.s3_medallion.bucket_arns["gold"]

  # ADR 0011 (amended 2026-09-01): DISABLED unless a compute exercise is
  # active -- see variables.tf.
  pipeline_active = var.pipeline_active
}

module "observability" {
  source = "../../modules/observability"

  state_machine_arn     = module.step_functions.state_machine_arn
  ingestion_lambda_name = module.lambda_ingestion.function_name
  athena_workgroup_name = module.athena.workgroup_name

  bronze_bucket_name = module.s3_medallion.bucket_names["bronze"]
  bronze_bucket_arn  = module.s3_medallion.bucket_arns["bronze"]
  gold_bucket_name   = module.s3_medallion.bucket_names["gold"]
  gold_bucket_arn    = module.s3_medallion.bucket_arns["gold"]
}

module "github_oidc" {
  source = "../../modules/github_oidc"

  account_id = data.aws_caller_identity.current.account_id

  tfstate_bucket_arn        = "arn:aws:s3:::cerberus-platform-tfstate-131715059025"
  tfstate_lock_table_arn    = "arn:aws:dynamodb:us-east-1:${data.aws_caller_identity.current.account_id}:table/cerberus-platform-tfstate-lock"
  bucket_arns               = module.s3_medallion.bucket_arns
  athena_results_bucket_arn = module.athena.results_bucket_arn
}
