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

output "lineage_collector_url" {
  description = "Base URL of the 6.4b OpenLineage collector -- 6.4c sets this as the producers' OPENLINEAGE_URL."
  value       = module.lineage.collector_url
}

output "lineage_bucket_name" {
  description = "The 6.4b lineage event bucket name."
  value       = module.lineage.bucket_name
}

output "ci_plan_role_arn" {
  description = "cerberus-ci-plan IAM role ARN, for GitHub's repo variable/workflow reference."
  value       = module.github_oidc.ci_plan_role_arn
}

output "ci_apply_role_arn" {
  description = "cerberus-ci-apply IAM role ARN, for GitHub's repo variable/workflow reference."
  value       = module.github_oidc.ci_apply_role_arn
}

output "prometheus_workspace_arn" {
  description = "7.7: AMP workspace ARN -- read by envs/dev-compute via terraform_remote_state, to scope the Prometheus/Grafana IRSA roles' aps:* grants."
  value       = module.prometheus_workspace.workspace_arn
}

output "prometheus_endpoint" {
  description = "7.7: AMP workspace's Prometheus-compatible base URL -- read by envs/dev-compute for Grafana's AMP data source, and for local PromQL queries."
  value       = module.prometheus_workspace.prometheus_endpoint
}

output "prometheus_remote_write_url" {
  description = "7.7: AMP remote-write URL -- read by envs/dev-compute for the in-cluster Prometheus agent."
  value       = module.prometheus_workspace.remote_write_url
}

output "console_subnet_id" {
  description = "9.2: console subnet ID (ADR 0024) -- read by the future envs/dev-console via terraform_remote_state."
  value       = module.vpc.console_subnet_id
}

output "console_route_table_id" {
  description = "9.2: console route table ID -- read by the future envs/dev-console via terraform_remote_state, to attach a session NAT route."
  value       = module.vpc.console_route_table_id
}

output "grafana_read_role_arn" {
  description = "9.2: cerberus-grafana-read IAM role ARN -- assumed by `make grafana-up` for the local Grafana."
  value       = module.console_roles.grafana_read_role_arn
}

output "console_cli_role_arn" {
  description = "9.2: cerberus-console-cli IAM role ARN -- the role the console commands run as."
  value       = module.console_roles.console_cli_role_arn
}

output "console_url" {
  description = "9.2: the console's public URL (CloudFront)."
  value       = "https://${module.console_edge.distribution_domain_name}"
}

output "console_distribution_id" {
  description = "9.2: CloudFront distribution ID -- 9.4's publish invalidates it."
  value       = module.console_edge.distribution_id
}

output "console_site_bucket_name" {
  description = "9.2: site bucket name -- 9.4's publish syncs the built site here."
  value       = module.console_edge.site_bucket_name
}

output "console_user_pool_id" {
  description = "9.2: Cognito user pool ID -- the owner creates invited users with admin-create-user."
  value       = module.console_edge.user_pool_id
}

output "console_client_id" {
  description = "9.2: Cognito app client ID of the console SPA."
  value       = module.console_edge.client_id
}

output "console_auth_domain" {
  description = "9.2: Cognito hosted-UI base URL."
  value       = module.console_edge.auth_domain
}

output "console_api_path" {
  description = "9.2: path of the command route, same-origin behind CloudFront."
  value       = "/api/command"
}

output "console_callback_url" {
  description = "9.2: the app client's sign-in redirect URL."
  value       = module.console_edge.callback_url
}

output "console_api_id" {
  description = "9.2: API Gateway HTTP API ID of the command route."
  value       = module.console_edge.api_id
}
