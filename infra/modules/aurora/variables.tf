variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "app_security_group_ids" {
  description = "Security groups (API + workers) allowed to reach Postgres on 5432"
  type        = list(string)
}

variable "engine_version" {
  type    = string
  default = "16.6"
}

variable "min_acu" {
  type    = number
  default = 0.5
}

variable "max_acu" {
  type    = number
  default = 4
}

variable "backup_retention_days" {
  description = "PITR window (specs/08-security-compliance.md: Aurora PITR 35 days in prod)"
  type        = number
  default     = 7
}

variable "deletion_protection" {
  type    = bool
  default = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
