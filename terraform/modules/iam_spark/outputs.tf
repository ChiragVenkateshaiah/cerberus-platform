output "role_arn" {
  description = "cerberus-spark IAM role ARN, for spark_job's service-account annotation."
  value       = aws_iam_role.spark.arn
}
