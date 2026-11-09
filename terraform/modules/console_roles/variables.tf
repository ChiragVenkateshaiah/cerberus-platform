variable "account_id" {
  description = "AWS account ID, used to build the Step Functions execution ARN pattern."
  type        = string
}

variable "region" {
  description = "AWS region, used to build the Step Functions execution ARN pattern."
  type        = string
  default     = "us-east-1"
}

variable "trusted_principal_arn" {
  description = "The IAM principal (cerberus-admin) allowed to assume both roles by hand, as in the iam module."
  type        = string
}

variable "amp_workspace_arn" {
  description = "ARN of the AMP workspace that cerberus-grafana-read may query."
  type        = string
}

variable "state_machine_arn" {
  description = "ARN of the orchestration state machine that cerberus-console-cli may describe and list."
  type        = string
}

variable "state_machine_name" {
  description = "Name of the orchestration state machine, used to scope the execution ARN pattern."
  type        = string
}
