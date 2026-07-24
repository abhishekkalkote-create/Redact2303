variable "name" {
  description = "Name prefix for VPC resources, e.g. redactproof-dev"
  type        = string
}

variable "cidr_block" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  type    = number
  default = 2
}

variable "nat_gateway_count" {
  description = "1 for dev/staging (cost), == az_count for prod (AZ-resilient)"
  type        = number
  default     = 1
}

variable "tags" {
  type    = map(string)
  default = {}
}
