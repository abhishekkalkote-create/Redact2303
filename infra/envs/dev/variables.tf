variable "env" {
  type    = string
  default = "dev"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "domain_name" {
  description = "Public hostname once DNS exists, e.g. dev.redactproof.com. Empty = *.cloudfront.net."
  type        = string
  default     = ""
}

variable "public_hostname" {
  description = <<-EOT
    The real public hostname to use for CORS_ORIGINS whenever domain_name is still
    empty - deliberately a plain string variable, not a `module.edge.*` reference.
    module.edge already depends on module.ecs (its origin is module.ecs.alb_dns_name),
    so module.ecs referencing any module.edge output directly would form a real
    dependency cycle (ecs -> edge -> ecs). Set this to module.edge's own
    cloudfront_domain_name output by hand (it's stable once the distribution exists,
    e.g. via `terraform output cloudfront_domain_name`) after the first apply, then
    keep it in sync only if the distribution is ever replaced.
  EOT
  type        = string
  default     = ""
}

variable "cognito_domain_prefix" {
  type    = string
  default = "redactproof-dev"
}

variable "api_image" {
  type    = string
  default = ""
}

variable "web_image" {
  type    = string
  default = ""
}

variable "worker_image" {
  type    = string
  default = ""
}

variable "pagerduty_integration_email" {
  description = "See infra/modules/alerting/variables.tf — empty until a paging vendor account exists."
  type        = string
  default     = ""
}
