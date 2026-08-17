output "bucket_names" {
  description = "Map of layer -> bucket name."
  value       = module.s3_medallion.bucket_names
}

output "bucket_arns" {
  description = "Map of layer -> bucket ARN."
  value       = module.s3_medallion.bucket_arns
}

output "role_arns" {
  description = "Map of role name -> ARN (ingestion/transform/serving)."
  value       = module.iam.role_arns
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

output "eks_cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "spark_jobs_namespace" {
  description = "Kubernetes namespace the Spark Operator watches for SparkApplication resources -- where 3.5's job belongs."
  value       = module.spark_operator.jobs_namespace
}
