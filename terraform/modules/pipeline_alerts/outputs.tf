output "rule_group_namespace_name" {
  description = "The AMP rule-group namespace name -- for `aws amp describe-rule-groups-namespace --name`."
  value       = aws_prometheus_rule_group_namespace.status.name
}
