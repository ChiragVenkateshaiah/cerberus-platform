# ADR 0011 (amended 2026-09-01): the pipeline-activity switch.
#
# The daily orchestrated run (aws_scheduler_schedule.daily in the
# step_functions module) is DISABLED unless a compute exercise is active,
# because its RunTransform step submits a Spark job to the envs/dev-compute
# EKS cluster, which is destroyed between exercises by design (ADR
# 0007/0011). Since 4.3 folded the platform's only schedule into the state
# machine's parent, ingestion rides on the same switch -- the whole
# pipeline is dormant while dev-compute is down, which is the normal state.
#
# This is a committed default, not a local -var override, on purpose: CI
# applies dev-standing on every terraform-touching merge with no -var
# flags, so a local override would be silently reverted to false by the
# next merge. Flipping this to true (and back) is a small visible PR that
# brackets a compute exercise -- see docs/adr/0011 and
# terraform/envs/dev-compute/main.tf's header for the runbook.
variable "pipeline_active" {
  description = "Whether a compute exercise is active. true = the daily orchestration schedule is ENABLED and 6.2's pipeline-health / data-freshness alarms exist; false (default) = schedule DISABLED and those alarms not created (every signal is legitimately stale while the pipeline is dormant)."
  type        = bool
  default     = false
}

# 6.2: the address subscribed to the cerberus-pipeline-alerts SNS topic.
# Committed here (like pipeline_active) rather than a local -var override,
# for the same reason -- CI applies this root with no -var flags, so an
# override would be reverted to nothing on the next merge. Same inbox as
# the Phase 0 cerberus-billing-alerts topic; already public in this repo's
# git-author history. After the first apply that creates the subscription,
# confirm it once via the link AWS emails to that address.
variable "alert_email" {
  description = "Email address subscribed to the cerberus-pipeline-alerts SNS topic (6.2)."
  type        = string
  default     = "chiragvenkateshaiah95@gmail.com"
}
