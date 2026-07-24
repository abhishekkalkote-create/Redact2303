variable "name" {
  type = string
}

variable "mfa_enforced" {
  description = "org policy can also require MFA at the app level; this is the pool-wide floor"
  type        = bool
  default     = false
}

variable "callback_urls" {
  type    = list(string)
  default = ["http://localhost:3000"]
}

variable "logout_urls" {
  type    = list(string)
  default = ["http://localhost:3000"]
}

variable "domain_prefix" {
  description = "Cognito hosted-UI domain prefix, e.g. 'redactproof-dev'. Empty = no hosted domain yet."
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
