variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "cerberus-platform-eks"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version. Left unset (null) so AWS picks its current default at apply time -- this cluster is spun up and destroyed per job (3.7), so there's no long-lived version to pin against upgrade drift."
  type        = string
  default     = null
}

variable "private_subnet_ids" {
  description = "Private subnet IDs from the vpc module -- where the control plane's cross-account ENIs and the worker node group both live."
  type        = list(string)
}

# ADR 0020 (8.8): two node groups. 3.3's choice stands for both: each group
# spans both private subnets and EKS's Auto Scaling group spreads instances
# across them.

variable "system_instance_types" {
  description = "On-Demand system node instance type(s). m7i-flex.large (2 vCPU / 8 GiB), the type the whole cluster ran on since 2026-08-18: enough for the operator, the monitoring stack, Cluster Autoscaler and one Spark driver."
  type        = list(string)
  default     = ["m7i-flex.large"]
}

variable "system_node_count" {
  description = "System node count (fixed: min = max = desired). 1 per ADR 0020; raise it if the driver and the system pods don't fit (8.8 checks)."
  type        = number
  default     = 1
}

variable "executor_instance_types" {
  description = "Spot executor instance types, all 4 vCPU / 16 GiB so Cluster Autoscaler's capacity estimate holds for any of them (EKS guide). Six types across Intel and AMD generations widen the Spot pools price-capacity-optimized can choose from. m7i-flex is left out: not certain it is offered as Spot. Each node fits four 1-core, 2 GB executors."
  type        = list(string)
  default     = ["m7i.xlarge", "m6i.xlarge", "m5.xlarge", "m7a.xlarge", "m6a.xlarge", "m5a.xlarge"]
}

variable "executor_desired_size" {
  description = "Spot executor nodes for this exercise, as both min and desired size (dev-compute's executor_nodes): Ready before the run, and never scaled below. 0 leaves every executor node to Cluster Autoscaler, which takes minutes per scale-up."
  type        = number
  default     = 1
}

variable "executor_max_size" {
  description = "Upper bound for Cluster Autoscaler. 4 x 4 vCPU = 16 Spot vCPU, half the account's 32 Spot vCPU quota (8.2)."
  type        = number
  default     = 4
}

variable "executor_taint_key" {
  description = "Taint on the Spot executor nodes; Spark executors and the image pre-pull DaemonSet tolerate it."
  type        = string
  default     = "cerberus/spot"
}
