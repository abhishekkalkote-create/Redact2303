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
