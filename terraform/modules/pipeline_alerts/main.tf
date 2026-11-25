# 10.4b (ADR 0021 and its amendments; plan 2026-11-20-status-dashboard-and-
# alerts.md 4.1 and 4.2). The pipeline-status alert rules and the AMP
# Alertmanager definition, both loaded from files in the repo so promtool and
# amtool test the same text that AMP runs (observability/alerts/, `make
# alerts-test`).
#
# The topic policy that lets AMP publish to the alerts topic lives with the
# topic, in the observability module -- this module only names the topic.
#
# CI plans and applies this (the cerberus-ci-apply statement
# ManageAmpRulesAndAlerting), and observability/alerts/** is in the workflow
# path filters, so a change to either file reaches AMP on merge.

locals {
  alerts_dir = "${path.module}/../../../observability/alerts"
}

# One namespace, one group (cerberus-status). The name is the namespace's
# identity in AMP: renaming it replaces the rules.
resource "aws_prometheus_rule_group_namespace" "status" {
  name         = "cerberus-status"
  workspace_id = var.workspace_id
  data         = file("${local.alerts_dir}/status.rules.yaml")
}

# templatefile() fills one variable, topic_arn. The Go templates in the file
# use {{ }} only, which Terraform leaves alone.
resource "aws_prometheus_alert_manager_definition" "status" {
  workspace_id = var.workspace_id
  definition = templatefile("${local.alerts_dir}/alertmanager.yaml.tftpl", {
    topic_arn = var.alerts_topic_arn
  })
}
