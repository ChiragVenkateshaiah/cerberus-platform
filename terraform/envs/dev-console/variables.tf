variable "minutes" {
  description = "Session length in minutes (ADR 0024: default 90, cap 120 -- Grafana's own login maximum is 2 h). Sets live.json's `ends`. The instance shuts itself down at boot + minutes + 30."
  type        = number
  default     = 90

  validation {
    condition     = var.minutes >= 1 && var.minutes <= 120 && var.minutes == floor(var.minutes)
    error_message = "minutes must be a whole number from 1 to 120."
  }
}
