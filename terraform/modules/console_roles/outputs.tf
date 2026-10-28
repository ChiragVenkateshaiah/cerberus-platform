output "grafana_read_role_arn" {
  description = "cerberus-grafana-read IAM role ARN -- what `make grafana-up` assumes for the local Grafana."
  value       = aws_iam_role.grafana_read.arn
}

output "grafana_read_role_name" {
  description = "cerberus-grafana-read IAM role name."
  value       = aws_iam_role.grafana_read.name
}

output "console_cli_role_arn" {
  description = "cerberus-console-cli IAM role ARN -- the role the console commands run as."
  value       = aws_iam_role.console_cli.arn
}

output "console_cli_role_name" {
  description = "cerberus-console-cli IAM role name."
  value       = aws_iam_role.console_cli.name
}
