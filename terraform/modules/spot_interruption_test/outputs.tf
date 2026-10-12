output "template_id" {
  description = "FIS experiment template ID -- exercise.sh --interrupt-spot starts it with `aws fis start-experiment`."
  value       = aws_fis_experiment_template.spot_interruption.id
}

output "role_arn" {
  description = "The FIS experiment role."
  value       = aws_iam_role.fis.arn
}
