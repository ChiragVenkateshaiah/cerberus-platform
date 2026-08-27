output "bucket_names" {
  description = "Map of layer -> bucket name."
  value       = module.s3_medallion.bucket_names
}

output "bucket_arns" {
  description = "Map of layer -> bucket ARN."
  value       = module.s3_medallion.bucket_arns
}

output "role_arns" {
  description = "Map of role name -> ARN (ingestion/transform/serving/ingestion_lambda/orchestration_*). cerberus-spark lives in envs/dev-compute, not here."
  value       = module.iam.role_arns
}

output "orchestration_transform_role_arn" {
  description = "cerberus-orchestration-transform IAM role ARN -- read by envs/dev-compute's spark_job module via terraform_remote_state, for its EKS access entry."
  value       = module.iam.orchestration_transform_role_arn
}

output "glue_database_name" {
  description = "Glue database name."
  value       = module.glue_catalog.database_name
}

output "glue_table_names" {
  description = "Map of logical name -> Glue table name."
  value       = module.glue_catalog.table_names
}

output "athena_workgroup_name" {
  description = "Athena workgroup name."
  value       = module.athena.workgroup_name
}

output "athena_results_bucket_name" {
  description = "Athena query-results bucket name."
  value       = module.athena.results_bucket_name
}

output "vpc_id" {
  description = "VPC ID -- read by envs/dev-compute's eks/vpc_nat modules via terraform_remote_state."
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs -- read by envs/dev-compute's eks module via terraform_remote_state."
  value       = module.vpc.private_subnet_ids
}

output "public_subnet_a_id" {
  description = "public-a's subnet ID -- read by envs/dev-compute's vpc_nat module via terraform_remote_state, for NAT Gateway placement."
  value       = module.vpc.public_subnet_a_id
}

output "private_route_table_id" {
  description = "Private route table ID -- read by envs/dev-compute's vpc_nat module via terraform_remote_state, to attach the NAT route."
  value       = module.vpc.private_route_table_id
}

output "pipeline_dashboard_url" {
  description = "Console URL for the 6.1 pipeline observability dashboard."
  value       = module.observability.dashboard_url
}

output "freshness_probe_function_name" {
  description = "The 6.1 data-freshness probe Lambda's name."
  value       = module.observability.freshness_probe_function_name
}

output "ci_plan_role_arn" {
  description = "cerberus-ci-plan IAM role ARN, for GitHub's repo variable/workflow reference."
  value       = module.github_oidc.ci_plan_role_arn
}

output "ci_apply_role_arn" {
  description = "cerberus-ci-apply IAM role ARN, for GitHub's repo variable/workflow reference."
  value       = module.github_oidc.ci_apply_role_arn
}
