variable "account_id" {
  description = "AWS account ID. Used only to build the bucket names and the SSM parameter ARN."
  type        = string
}

variable "region" {
  description = "AWS region. CloudFront logging v2 delivery sources and the Function live in us-east-1."
  type        = string
  default     = "us-east-1"
}

variable "public_key_pem" {
  description = "PEM of the CloudFront signing public key. Null uses default_public_key.pem, whose private half was discarded at generation (PREWARM holds no usable key, ADR 0030 Decision 4). A live session passes the public half of its own tmpfs key."
  type        = string
  default     = null
}

variable "release_at_epoch" {
  description = "Release time in epoch seconds, written to the KeyValueStore key release_at. The default is a far-future sentinel (2100-01-01 UTC). A live apply passes an explicit value; never timestamp()."
  type        = number
  default     = 4102444800

  validation {
    condition     = var.release_at_epoch > 0 && var.release_at_epoch == floor(var.release_at_epoch)
    error_message = "release_at_epoch must be a whole number above 0."
  }
}

# --- Load generator (load_gen.tf). Off by default: PREWARM has no instance. ---

variable "create_load_gen" {
  description = "Create the Spot load generator, its role, instance profile and security group. False means count 0 for all of them."
  type        = bool
  default     = false
}

variable "vpc_id" {
  description = "VPC for the load generator security group (dev-standing vpc_id). Read only when create_load_gen is true."
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Public subnet for the load generator (dev-standing public_subnet_a_id). Read only when create_load_gen is true."
  type        = string
  default     = ""
}

variable "minutes" {
  description = "Session length in minutes (1 to 120, as ADR 0024 for the console). Sets the instance self-shutdown with shutdown_margin_minutes."
  type        = number
  default     = 90

  validation {
    condition     = var.minutes >= 1 && var.minutes <= 120 && var.minutes == floor(var.minutes)
    error_message = "minutes must be a whole number from 1 to 120."
  }
}

variable "shutdown_margin_minutes" {
  description = "The instance shuts itself down at boot + minutes + this margin. 45 is the console's margin; 17.4 sets the final value (unverified)."
  type        = number
  default     = 45

  validation {
    condition     = var.shutdown_margin_minutes >= 0 && var.shutdown_margin_minutes == floor(var.shutdown_margin_minutes)
    error_message = "shutdown_margin_minutes must be a whole number, 0 or more."
  }
}

variable "instance_type" {
  description = "Graviton network-optimised type for the load generator. Unverified default; 17.4 fixes the size against the 5 Gbps byte plan."
  type        = string
  default     = "c6gn.xlarge"
}

variable "cookie_parameter_name" {
  description = "Name of the SSM SecureString that holds the session cookies. Created outside Terraform by launch-session; the role may read exactly this one."
  type        = string
  default     = "/cerberus/launch/session-cookies"

  validation {
    condition     = startswith(var.cookie_parameter_name, "/cerberus/launch/")
    error_message = "The parameter must be under /cerberus/launch/ (the cerberus-admin launch grant)."
  }
}

variable "k6_version" {
  description = "Pinned k6 version. Empty and unused until 17.4."
  type        = string
  default     = ""
}

variable "k6_sha256" {
  description = "sha256 of the pinned k6 archive. Empty and unused until 17.4."
  type        = string
  default     = ""
}
