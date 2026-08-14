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

# 3.3: a single managed node group spanning both private subnets, not one
# per AZ -- EKS's own Auto Scaling group spreads instances across whichever
# subnets it's given. Fixed size (desired = min = max), not autoscaling: this
# cluster runs one job then gets destroyed (3.7), so there's no steady-state
# demand curve to autoscale against.

variable "node_instance_types" {
  description = "Worker node instance type(s). m5.large: enough headroom for a small Spark driver/executor's JVM heap over EKS's own system pod overhead, without over-provisioning a cluster that's torn down within the hour."
  type        = list(string)
  default     = ["m5.large"]
}

variable "node_desired_size" {
  description = "Desired worker node count. 2: one per AZ, matching the two-AZ spread this node group is placed across."
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum worker node count."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum worker node count."
  type        = number
  default     = 2
}
