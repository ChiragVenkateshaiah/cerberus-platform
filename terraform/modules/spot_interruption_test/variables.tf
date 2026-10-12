variable "cluster_name" {
  description = "EKS cluster name, for the template's description and tags."
  type        = string
}

variable "executor_node_group_name" {
  description = "The Spot executor node group. EKS tags its instances eks:nodegroup-name with this; the experiment targets that tag, and the role can interrupt nothing else."
  type        = string
}

variable "duration_before_interruption" {
  description = "FIS durationBeforeInterruption (ISO 8601, PT2M-PT15M). PT2M: the rebalance recommendation and the 2-minute interruption notice arrive at once -- the real Spot worst case."
  type        = string
  default     = "PT2M"
}
