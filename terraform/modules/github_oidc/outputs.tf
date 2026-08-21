output "ci_plan_role_arn" {
  description = "cerberus-ci-plan IAM role ARN -- GitHub Actions' terraform-plan.yml assumes this via OIDC for any branch/PR."
  value       = aws_iam_role.ci_plan.arn
}

output "ci_apply_role_arn" {
  description = "cerberus-ci-apply IAM role ARN -- GitHub Actions' terraform-apply.yml assumes this via OIDC, trusted only for refs/heads/main."
  value       = aws_iam_role.ci_apply.arn
}
