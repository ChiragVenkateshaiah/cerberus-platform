output "role_arns" {
  description = "Map of role name -> ARN (ingestion/transform/serving/ingestion_lambda/spark/orchestration_transform/orchestration_dbt/orchestration_ecs_execution/orchestration_state_machine)."
  value = {
    ingestion                   = aws_iam_role.ingestion.arn
    transform                   = aws_iam_role.transform.arn
    serving                     = aws_iam_role.serving.arn
    ingestion_lambda            = aws_iam_role.ingestion_lambda.arn
    spark                       = aws_iam_role.spark.arn
    orchestration_transform     = aws_iam_role.orchestration_transform.arn
    orchestration_dbt           = aws_iam_role.orchestration_dbt.arn
    orchestration_ecs_execution = aws_iam_role.orchestration_ecs_execution.arn
    orchestration_state_machine = aws_iam_role.orchestration_state_machine.arn
  }
}

# Standalone, not read from role_arns -- same reasoning as
# ingestion_lambda_role_arn below: terraform/modules/step_functions needs
# this role's *name* (aws_iam_role_policy attaches by name, not ARN), and
# reading one key out of role_arns would still create a graph edge to
# every role in this module.
output "orchestration_state_machine_role_name" {
  description = "cerberus-orchestration-state-machine IAM role name, standalone."
  value       = aws_iam_role.orchestration_state_machine.name
}

output "orchestration_state_machine_role_arn" {
  description = "cerberus-orchestration-state-machine IAM role ARN, standalone -- same false-dependent risk as the other orchestration_* standalone outputs below."
  value       = aws_iam_role.orchestration_state_machine.arn
}

# Standalone, not read from role_arns -- discovered live during 3.7's
# destroy planning: a single consumer reading one key out of that map
# still creates a graph edge to the *entire* map expression, which depends
# on all 5 underlying role resources. Since spark's role is itself
# downstream of the EKS OIDC provider (destroyed/recreated on every Phase 3
# spin-up/destroy cycle), a `terraform destroy -target=module.eks` pulled
# in module.lambda_ingestion's Phase 2 resources as a false dependent --
# something completely unrelated to Phase 3. This output breaks that edge
# for lambda_ingestion specifically, without changing role_arns' shape for
# anything already reading it.
output "ingestion_lambda_role_arn" {
  description = "cerberus-ingestion-lambda IAM role ARN, standalone."
  value       = aws_iam_role.ingestion_lambda.arn
}

# Standalone, same reasoning as ingestion_lambda_role_arn above -- found
# live 2026-08-20 while planning 4.4's scoped destroy: orchestration_runner
# and step_functions both read individual keys out of role_arns, which
# created a graph edge to the *entire* map (all 9 roles), including spark.
# A `terraform destroy -target=module.iam.aws_iam_role.spark` pulled in
# orchestration_runner's task definitions and step_functions' whole state
# machine as false dependents -- resources with no real relationship to
# spark's role at all. These three break that edge for exactly the roles
# those two modules actually consume.
output "orchestration_transform_role_arn" {
  description = "cerberus-orchestration-transform IAM role ARN, standalone."
  value       = aws_iam_role.orchestration_transform.arn
}

output "orchestration_dbt_role_arn" {
  description = "cerberus-orchestration-dbt IAM role ARN, standalone."
  value       = aws_iam_role.orchestration_dbt.arn
}

output "orchestration_ecs_execution_role_arn" {
  description = "cerberus-orchestration-ecs-execution IAM role ARN, standalone."
  value       = aws_iam_role.orchestration_ecs_execution.arn
}
