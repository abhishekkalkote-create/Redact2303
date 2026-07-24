variable "name" {
  type = string
}

variable "alb_dns_name" {
  type = string
}

variable "alb_certificate_arn" {
  description = "Set once the ALB has a real ACM cert — switches the CloudFront origin to https-only"
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Public hostname, e.g. app.redactproof.com. Empty = use the default *.cloudfront.net domain."
  type        = string
  default     = ""
}

variable "cloudfront_certificate_arn" {
  description = "ACM cert in us-east-1 for var.domain_name (CloudFront requires us-east-1 certs regardless of app region)"
  type        = string
  default     = ""
}

variable "price_class" {
  type    = string
  default = "PriceClass_100" # US/Canada/Europe — matches "US-only" data residency intent
}

variable "rate_limit_per_5min" {
  type    = number
  default = 2000
}

variable "tags" {
  type    = map(string)
  default = {}
}
