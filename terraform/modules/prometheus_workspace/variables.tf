variable "retention_days" {
  description = "Days AMP keeps samples. Metrics only exist for dev-compute exercise windows (ADR 0016), so this bounds history, not volume. 400 days per ADR 0024: the 2026-10-13 and 8.10 runs stay viewable while the portfolio is in use. AWS allows 1-1095."
  type        = number
  default     = 400
}
