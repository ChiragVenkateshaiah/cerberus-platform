output "cluster_arn" {
  description = "The orchestration ECS cluster's ARN, for the step_functions module's RunTask parameters."
  value       = aws_ecs_cluster.this.arn
}

output "transform_task_definition_arn" {
  description = "The transform task definition's ARN (family:revision)."
  value       = aws_ecs_task_definition.transform.arn
}

output "dbt_task_definition_arn" {
  description = "The dbt task definition's ARN (family:revision)."
  value       = aws_ecs_task_definition.dbt.arn
}

output "security_group_id" {
  description = "The runner tasks' security group ID, for the step_functions module's NetworkConfiguration."
  value       = aws_security_group.runner.id
}
