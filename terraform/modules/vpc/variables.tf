variable "vpc_cidr" {
  description = "CIDR block for the dedicated VPC. ADR 0007: 10.0.0.0/16, distinct from the account's default 172.31.0.0/16."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "The two AZs this VPC spans. ADR 0007: enough to demonstrate multi-AZ without a third AZ's added resource count for a cluster that exists for one job's duration."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  description = "CIDR per public subnet, one per AZ, same order as availability_zones."
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR per private subnet, one per AZ, same order as availability_zones. Sized /20 for VPC CNI per-pod IP headroom (ADR 0007)."
  type        = list(string)
  default     = ["10.0.16.0/20", "10.0.32.0/20"]
}

variable "region" {
  description = "AWS region, used to build the S3 Gateway VPC endpoint's service name."
  type        = string
  default     = "us-east-1"
}
