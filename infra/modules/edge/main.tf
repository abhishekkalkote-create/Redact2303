# CloudFront in front of the ALB + a WAFv2 web ACL (managed rule groups + rate limiting).
# specs/08-security-compliance.md: "WAF: managed rules + rate-based; ... strict CSP; no
# third-party scripts on app pages." CSP/security headers are set by the app itself
# (Next.js middleware / FastAPI), not here.
#
# WAFv2 for CloudFront must be created in us-east-1 — see providers.tf's aliased provider
# passed in as var.waf_provider... Terraform can't alias providers *inside* a child module
# from a variable, so callers must pass a us-east-1 provider via `providers = { aws = ... }`
# when instantiating this module (see envs/dev/main.tf).

resource "aws_wafv2_web_acl" "this" {
  name        = var.name
  description = "${var.name} edge WAF — managed rules + rate limiting"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 0
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name}-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name}-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "RateLimitPerIp"
    priority = 2
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = var.rate_limit_per_5min
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = var.name
    sampled_requests_enabled   = true
  }

  tags = var.tags
}

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = var.name
  web_acl_id      = aws_wafv2_web_acl.this.arn
  price_class     = var.price_class
  aliases         = var.domain_name == "" ? [] : [var.domain_name]

  origin {
    domain_name = var.alb_dns_name
    origin_id   = "alb"
    custom_origin_config {
      # http-only until the ALB has a real ACM cert (see modules/ecs var.certificate_arn) —
      # CloudFront still terminates TLS for end users regardless.
      origin_protocol_policy = var.alb_certificate_arn == "" ? "http-only" : "https-only"
      http_port              = 80
      https_port             = 443
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.domain_name == "" ? true : null
    acm_certificate_arn            = var.domain_name == "" ? null : var.cloudfront_certificate_arn
    ssl_support_method             = var.domain_name == "" ? null : "sni-only"
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  tags = var.tags
}

# AWS-managed policies: "CachingDisabled" (dynamic app, not a CDN cache target in Phase 0)
# and "AllViewer" (forward everything — auth headers, cookies — to the ALB/app).
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}
