variable "name" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

# --- Wiring from other modules (no cross-module resource references here, so this module
# stays independently plannable/testable — see main.tf's module docstring) ---

variable "dlq_names" {
  description = "queue_type => DLQ name, from module.queues.dlq_names."
  type        = map(string)
}

variable "ecs_cluster_name" {
  type = string
}

variable "api_service_name" {
  type = string
}

variable "web_service_name" {
  type = string
}

variable "worker_service_name" {
  type = string
}

variable "alb_arn_suffix" {
  type = string
}

variable "api_target_group_arn_suffix" {
  type = string
}

variable "web_target_group_arn_suffix" {
  type = string
}

variable "api_log_group_name" {
  description = <<-EOT
    module.ecs.api_log_group_name — where app/core/logging.py's JSON lines land via the
    awslogs driver. Feeds the rls_violation / export.integrity_failed log-based metric
    filters (see main.tf) — the two specs/02-architecture.md alarms that had no metric to
    alarm on before app/core/logging.py existed.
  EOT
  type        = string
}

# --- Where alarms page (the piece this repo can't wire up on its own — see main.tf) ---

variable "pagerduty_integration_email" {
  description = <<-EOT
    PagerDuty (or any paging vendor) email-integration address for the on-call service
    this alerting is meant to page. Empty by default: no vendor account exists yet to get
    this address from (specs/10-build-plan.md Phase 6's on-call rotation is unbuilt for
    exactly that reason). Once one exists, set this and `terraform apply` subscribes it —
    no other change needed. Deliberately NOT the PagerDuty Terraform provider (that needs
    a PagerDuty API key/account this repo doesn't have); SNS-to-email is the one on-call
    wiring path that needs nothing but an email address.
  EOT
  type        = string
  default     = ""
}

# --- Alarm thresholds (sensible defaults; override per environment) ---

variable "dlq_message_count_threshold" {
  description = "Any DLQ having >= this many visible messages pages on-call (specs/02-architecture.md: \"DLQ non-empty\")."
  type        = number
  default     = 1
}

variable "alb_5xx_count_threshold" {
  description = "ALB-level 5xx responses in a 5-minute window."
  type        = number
  default     = 5
}

variable "alb_p95_latency_seconds_threshold" {
  description = <<-EOT
    ALB TargetResponseTime p95, in seconds. This is a general API-responsiveness signal,
    NOT a literal check of specs/01-product-spec.md US-6's per-action 300ms review-action
    SLO — that needs an app-emitted custom metric (per-endpoint latency), which doesn't
    exist yet (see load-test/README.md's finding re: bulk-approve latency). This alarm is
    the coarse, always-available proxy in the meantime.
  EOT
  type        = number
  default     = 2
}

variable "ecs_cpu_high_threshold_percent" {
  type    = number
  default = 85
}

variable "ecs_memory_high_threshold_percent" {
  type    = number
  default = 85
}

variable "rls_violation_count_threshold" {
  description = "Any occurrence pages on-call (specs/02-architecture.md's own wording for this alarm)."
  type        = number
  default     = 1
}

variable "integrity_verifier_failure_count_threshold" {
  description = "Any occurrence pages on-call (specs/02-architecture.md's own wording for this alarm) — a blocked export is not routine."
  type        = number
  default     = 1
}
