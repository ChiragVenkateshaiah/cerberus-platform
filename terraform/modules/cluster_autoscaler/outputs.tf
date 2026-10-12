output "role_arn" {
  description = "Cluster Autoscaler's IRSA role."
  value       = aws_iam_role.autoscaler.arn
}
