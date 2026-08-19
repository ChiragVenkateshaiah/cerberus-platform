variable "account_id" {
  description = "AWS account ID."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = "VPC ID (vpc module) -- for the runner tasks' security group."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs (vpc module) -- where the Fargate tasks run, same as the EKS node group."
  type        = list(string)
}

variable "transform_task_role_arn" {
  description = "cerberus-orchestration-transform IAM role ARN (iam module) -- the transform task's own role."
  type        = string
}

variable "dbt_task_role_arn" {
  description = "cerberus-orchestration-dbt IAM role ARN (iam module) -- the dbt task's own role."
  type        = string
}

variable "task_execution_role_arn" {
  description = "cerberus-orchestration-ecs-execution IAM role ARN (iam module) -- shared by both task definitions for ECR pull + CloudWatch Logs delivery, distinct from either task's own role."
  type        = string
}

variable "silver_bucket_name" {
  description = "Silver bucket name (s3_medallion module) -- where the transform task uploads promote_payments_spark.py before submitting it."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster name (eks module) -- the transform task's CLUSTER_NAME env var."
  type        = string
}

variable "glue_database_name" {
  description = "Glue database name (glue_catalog module) -- the transform task's GLUE_DATABASE env var."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup name (athena module) -- the transform task's ATHENA_WORKGROUP env var."
  type        = string
}
