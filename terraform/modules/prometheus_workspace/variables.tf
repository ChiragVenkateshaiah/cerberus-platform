variable "retention_days" {
  description = "Days AMP keeps samples. Metrics only exist for dev-compute exercise windows (ADR 0016), so this bounds history, not volume. 90 days matches the lineage event retention -- enough to compare the 7.7 exercise against the 7.8 demo and anything after it. AWS allows 1-1095; its implicit default is 150."
  type        = number
  default     = 90
}
