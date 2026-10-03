# 7.7 (Phase 7 -- Prometheus for the EKS/Spark layer). The Amazon Managed
# Service for Prometheus (AMP) workspace ADR 0016 chose as the metrics
# store: docs/adr/0016-prometheus-for-eks-spark.md.
#
# Instantiated from envs/dev-standing, not dev-compute: AMP has no
# workspace fee (it bills per sample ingested, per GB stored, per query
# sample), so it costs nothing idle and survives every dev-compute
# teardown -- the metrics outlive the cluster that produced them. The
# writers and readers (the in-cluster Prometheus agent and Grafana) live
# in envs/dev-compute and read this module's endpoints through
# terraform_remote_state.standing.
#
# Nothing here grants access to the workspace. aps:RemoteWrite and the
# query actions are granted per identity: the two IRSA roles in
# dev-compute, and cerberus-admin's own policy for local querying.

resource "aws_prometheus_workspace" "this" {
  alias = "cerberus-platform"

  tags = {
    Phase     = "7"
    Component = "prometheus"
  }
}

# Retention stated in code rather than left at AWS's implicit 150-day
# default, the same way every bucket and log group in this repo states its
# lifecycle. AMP's workspace configuration is a separate resource from the
# workspace itself.
resource "aws_prometheus_workspace_configuration" "this" {
  workspace_id             = aws_prometheus_workspace.this.id
  retention_period_in_days = var.retention_days
}
