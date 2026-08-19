# 4.2: shared root-module locals so values that have to agree across two
# otherwise-independent modules can't drift into two different literals.
# orchestration_transform_k8s_group: spark_job's own EKS access entry maps
# cerberus-orchestration-transform's role to this Kubernetes group, and its
# RoleBinding grants RBAC to that same group name -- one module, but kept
# as a shared local anyway since eks_cluster_name (below) has to be, and
# splitting the two would be inconsistent for no reason.
# eks_cluster_name: passed explicitly to module.eks (its cluster_name),
# module.iam (eks_cluster_name, used only to build an ARN for
# cerberus-orchestration-transform's eks:DescribeCluster grant), and
# module.spark_job (its own access entry's cluster_name) instead of
# relying on defaults happening to match across three places.
locals {
  orchestration_transform_k8s_group = "cerberus-orchestration-transform"
  eks_cluster_name                  = "cerberus-platform-eks"
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

  eks_oidc_provider_arn = module.eks.oidc_provider_arn
  eks_oidc_issuer_url   = module.eks.oidc_issuer_url

  eks_cluster_name = local.eks_cluster_name
}

module "lambda_ingestion" {
  source = "../../modules/lambda_ingestion"

  bronze_bucket_name = module.s3_medallion.bucket_names["bronze"]
  execution_role_arn = module.iam.ingestion_lambda_role_arn
}

module "vpc" {
  source = "../../modules/vpc"
}

module "eks" {
  source = "../../modules/eks"

  cluster_name       = local.eks_cluster_name
  private_subnet_ids = module.vpc.private_subnet_ids
}

module "spark_operator" {
  source = "../../modules/spark_operator"

  # Waits for the whole eks module -- cluster and node group both -- so the
  # operator's controller/webhook pods aren't scheduled before any node
  # exists to run them on.
  depends_on = [module.eks]
}

module "spark_job" {
  source = "../../modules/spark_job"

  namespace = module.spark_operator.jobs_namespace
  role_arn  = module.iam.role_arns["spark"]

  # 4.2: this module's own EKS access entry (main.tf) for the
  # orchestration transform task, alongside the RBAC that grants it.
  cluster_name                             = local.eks_cluster_name
  orchestration_transform_role_arn         = module.iam.role_arns["orchestration_transform"]
  orchestration_transform_kubernetes_group = local.orchestration_transform_k8s_group
}

module "orchestration_runner" {
  source = "../../modules/orchestration_runner"

  account_id         = data.aws_caller_identity.current.account_id
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  transform_task_role_arn = module.iam.role_arns["orchestration_transform"]
  dbt_task_role_arn       = module.iam.role_arns["orchestration_dbt"]
  task_execution_role_arn = module.iam.role_arns["orchestration_ecs_execution"]

  silver_bucket_name    = module.s3_medallion.bucket_names["silver"]
  cluster_name          = local.eks_cluster_name
  glue_database_name    = module.glue_catalog.database_name
  athena_workgroup_name = module.athena.workgroup_name
}

module "step_functions" {
  source = "../../modules/step_functions"

  account_id = data.aws_caller_identity.current.account_id

  state_machine_role_arn  = module.iam.role_arns["orchestration_state_machine"]
  state_machine_role_name = module.iam.orchestration_state_machine_role_name

  ingestion_lambda_arn          = module.lambda_ingestion.function_arn
  ecs_cluster_arn               = module.orchestration_runner.cluster_arn
  transform_task_definition_arn = module.orchestration_runner.transform_task_definition_arn
  dbt_task_definition_arn       = module.orchestration_runner.dbt_task_definition_arn
  transform_task_role_arn       = module.iam.role_arns["orchestration_transform"]
  dbt_task_role_arn             = module.iam.role_arns["orchestration_dbt"]
  task_execution_role_arn       = module.iam.role_arns["orchestration_ecs_execution"]

  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_id  = module.orchestration_runner.security_group_id

  athena_workgroup_name     = module.athena.workgroup_name
  athena_database_name      = module.glue_catalog.database_name
  athena_results_bucket_arn = module.athena.results_bucket_arn
  gold_bucket_arn           = module.s3_medallion.bucket_arns["gold"]
}
