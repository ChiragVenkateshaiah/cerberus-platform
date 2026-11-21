variable "workspace_id" {
  description = "AMP workspace ID (prometheus_workspace module output) -- the workspace the rules and the Alertmanager definition are loaded into."
  type        = string
}

variable "alerts_topic_arn" {
  description = "The cerberus-pipeline-alerts SNS topic ARN (observability module output) -- the Alertmanager's only receiver. Its policy must allow aps.amazonaws.com to publish from this workspace."
  type        = string
}
