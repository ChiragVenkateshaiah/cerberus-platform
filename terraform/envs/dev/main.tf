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
}

module "lambda_ingestion" {
  source = "../../modules/lambda_ingestion"

  bronze_bucket_name = module.s3_medallion.bucket_names["bronze"]
  execution_role_arn = module.iam.role_arns["ingestion_lambda"]
}

module "vpc" {
  source = "../../modules/vpc"
}

module "eks" {
  source = "../../modules/eks"

  private_subnet_ids = module.vpc.private_subnet_ids
}
