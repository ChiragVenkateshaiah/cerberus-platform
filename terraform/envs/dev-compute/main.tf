# ADR 0011 (5.1): the human-run, spin-up/destroy half of what used to be
# one envs/dev root. Holds the VPC's NAT Gateway/EIP, EKS, the Spark
# Operator, the Spark job's service account, cerberus-spark's IAM role,
# and (7.7) the Prometheus agent + Grafana with their IRSA roles
# -- every genuinely billed piece, brought up per exercise and torn down
# afterward (ADR 0007/0009). Never touched by CI; GitHub Actions' state has
# no permissions on any resource this root manages.
#
# See provider.tf's terraform_remote_state.standing for the one-directional
# read of envs/dev-standing's outputs this root depends on.
#
# --- Compute-exercise runbook (ADR 0011, amended 2026-09-01) ----------
# The daily orchestration schedule in dev-standing is DISABLED by default
# because RunTransform needs the EKS cluster this root creates. To run a
# real end-to-end exercise:
#
#   1. In dev-standing, set `pipeline_active = true` (variables.tf) and
#      merge it -- CI applies it, flipping the schedule to ENABLED. (Or
#      `make standing-apply` locally with the committed change.)
#   2. `make compute-apply`  -- brings up NAT/EKS/Spark here.
#   3. Run the pipeline (scheduled, or start an execution by hand).
#   4. `make compute-destroy` -- tears this back down.
#   5. In dev-standing, set `pipeline_active = false` and merge -- schedule
#      back to DISABLED. Do this even if step 4 slipped: a live schedule
#      with no cluster just fails RunTransform daily.
#
# Since 8.3, `make exercise` runs steps 2-4 as one command with no pauses
# (orchestration/exercise.sh): plan+apply, start an execution by hand,
# collect the metrics, destroy -- the destroy runs even after a failure or
# Ctrl-C. A manual execution doesn't need the schedule, so steps 1 and 5
# are only for multi-day exercises or for testing the gated alarms.

locals {
  orchestration_transform_k8s_group = "cerberus-orchestration-transform"
  eks_cluster_name                  = "cerberus-platform-eks"
}

module "vpc_nat" {
  source = "../../modules/vpc_nat"

  public_subnet_id       = data.terraform_remote_state.standing.outputs.public_subnet_a_id
  private_route_table_id = data.terraform_remote_state.standing.outputs.private_route_table_id
}

module "eks" {
  source = "../../modules/eks"

  cluster_name       = local.eks_cluster_name
  private_subnet_ids = data.terraform_remote_state.standing.outputs.private_subnet_ids
}

module "iam_spark" {
  source = "../../modules/iam_spark"

  bucket_arns           = data.terraform_remote_state.standing.outputs.bucket_arns
  eks_oidc_provider_arn = module.eks.oidc_provider_arn
  eks_oidc_issuer_url   = module.eks.oidc_issuer_url
}

module "spark_operator" {
  source = "../../modules/spark_operator"

  # Waits for the whole eks module -- cluster and node group both -- so the
  # operator's controller/webhook pods aren't scheduled before any node
  # exists to run them on.
  depends_on = [module.eks]
}

module "eks_observability" {
  source = "../../modules/eks_observability"

  cluster_name          = local.eks_cluster_name
  eks_oidc_provider_arn = module.eks.oidc_provider_arn
  eks_oidc_issuer_url   = module.eks.oidc_issuer_url

  # 7.7 (ADR 0016): the standing AMP workspace this layer writes to and
  # Grafana reads from.
  amp_workspace_arn       = data.terraform_remote_state.standing.outputs.prometheus_workspace_arn
  amp_remote_write_url    = data.terraform_remote_state.standing.outputs.prometheus_remote_write_url
  amp_prometheus_endpoint = data.terraform_remote_state.standing.outputs.prometheus_endpoint

  spark_jobs_namespace     = module.spark_operator.jobs_namespace
  spark_operator_namespace = module.spark_operator.operator_namespace

  # module.eks: no pods before nodes exist, same as spark_operator.
  # module.vpc_nat: forces the reverse on destroy -- the agent is torn down
  # (flushing its WAL to AMP through the NAT on shutdown) before the NAT
  # Gateway goes, per ADR 0016's teardown note. Without this edge the two
  # are unrelated in the graph and Terraform may destroy them in parallel.
  depends_on = [module.eks, module.vpc_nat]
}

module "spark_job" {
  source = "../../modules/spark_job"

  namespace = module.spark_operator.jobs_namespace
  role_arn  = module.iam_spark.role_arn

  cluster_name                             = local.eks_cluster_name
  orchestration_transform_role_arn         = data.terraform_remote_state.standing.outputs.orchestration_transform_role_arn
  orchestration_transform_kubernetes_group = local.orchestration_transform_k8s_group
}
