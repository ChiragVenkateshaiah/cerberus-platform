variable "public_subnet_id" {
  description = "Public subnet ID to place the NAT Gateway in (envs/dev-standing's vpc module, public-a). Read via terraform_remote_state, not a direct module reference."
  type        = string
}

variable "private_route_table_id" {
  description = "Private route table ID to attach the NAT route to (envs/dev-standing's vpc module). Read via terraform_remote_state, not a direct module reference."
  type        = string
}
