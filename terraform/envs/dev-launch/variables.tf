variable "public_key_pem" {
  description = "Public signing key (PEM). Null uses the module's committed default, whose private half was discarded (PREWARM). A live session passes the public half of its tmpfs key; it is public, not a secret."
  type        = string
  default     = null
}

variable "release_at_epoch" {
  description = "Release time in epoch seconds for /license. The default is a far-future sentinel; a live apply passes an explicit value. Never timestamp()."
  type        = number
  default     = 4102444800
}

variable "create_load_gen" {
  description = "Create the Spot load generator and its role and security group. False for PREWARM."
  type        = bool
  default     = false
}

variable "minutes" {
  description = "Session length in minutes, 1 to 120."
  type        = number
  default     = 90
}

variable "shutdown_margin_minutes" {
  description = "The instance shuts itself down at boot + minutes + this margin (unverified)."
  type        = number
  default     = 30
}

variable "instance_type" {
  description = "Load generator instance type (unverified default)."
  type        = string
  default     = "c6gn.xlarge"
}

variable "k6_version" {
  description = "Pinned k6 version (no leading v)."
  type        = string
  default     = "2.4.0"
}

variable "k6_sha256" {
  description = "sha256 of the pinned k6 linux-arm64 archive, from the release checksums file."
  type        = string
  default     = "7bb415f59d81ad649a86f6da6b3e1bd2e4e64e84909deef13e9bca70608abccb"
}

variable "budget_bytes" {
  description = "Ingress byte budget of the instance (planned bytes x 1.10, from launch/plan_bytes.py). 0 is refused when the instance is created."
  type        = number
  default     = 0
}
