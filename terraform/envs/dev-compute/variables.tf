variable "executor_nodes" {
  description = "Spot executor nodes for this exercise (ADR 0020): 4 vCPU / 16 GiB each, room for four 1-core, 2 GB executors. Set per run with `make exercise ARGS=\"--executor-nodes N\"` (exercise.sh passes -var). Becomes the executor group's min and desired size, so the nodes are Ready before the run."
  type        = number
  default     = 1
}
