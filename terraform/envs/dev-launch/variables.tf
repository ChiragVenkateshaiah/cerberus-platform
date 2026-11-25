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
  description = "The instance shuts itself down at boot + minutes + this margin (17.4 may change it)."
  type        = number
  default     = 45
}

variable "instance_type" {
  description = "Load generator instance type (unverified default; 17.4 fixes the size)."
  type        = string
  default     = "c6gn.xlarge"
}

variable "k6_version" {
  description = "Pinned k6 version (empty until 17.4)."
  type        = string
  default     = ""
}

variable "k6_sha256" {
  description = "sha256 of the pinned k6 archive (empty until 17.4)."
  type        = string
  default     = ""
}
