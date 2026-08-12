# specs/02-architecture.md § Observability: "Alarms: SLO breach, DLQ non-empty, RLS
# policy violation attempts (log + page on-call), integrity-verifier failure (blocks
# export, pages on-call)." specs/10-build-plan.md Phase 6: "on-call rotation + alarm
# tuning."
#
# What this module builds, and what it deliberately doesn't:
#
# - DLQ non-empty and a coarse SLO-breach proxy (ALB 5xx rate + p95 latency) are built
#   below — both derive from AWS-managed metrics that exist the moment the underlying
#   resources do, no app change required.
# - ECS CPU/memory alarms are included too — not in the spec's own alarm list, but a
#   standard, free health signal on the same services, so on-call isn't flying blind on
#   basic capacity issues while the metrics above are the ones actually named.
# - RLS-policy-violation and integrity-verifier-failure alarms ARE built, via log-based
#   metric filters against the API log group — app/core/logging.py now emits a single
#   JSON line per record, and app/core/errors.py's unhandled_error_handler /
#   app/services/export_service.py's create_export log an {"event": "rls_violation"} /
#   {"event": "export.integrity_failed"} line at exactly the moment specs/02 wants an
#   alarm. Neither log call includes the underlying content that made the event fire (see
#   both call sites' own docstrings/comments) — only counts and IDs, so this stays
#   content-free even feeding a metric filter on a log group anyone with CloudWatch
#   access to this AWS account could otherwise read.
# - The on-call ROTATION itself (who's on call, escalation policy, schedule) needs an
#   actual paging vendor account this repo doesn't have. What this module DOES provide is
#   the one vendor-account-free bridge to one: an SNS topic every alarm publishes to, plus
#   an optional email subscription (`var.pagerduty_integration_email`) — PagerDuty (and
#   most paging vendors) can turn a plain email address into a page, no API key needed.
#   Empty by default; set it once that address exists and apply again.

resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "pagerduty_email" {
  count     = var.pagerduty_integration_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.pagerduty_integration_email
}

# --- DLQ non-empty: one alarm per pipeline-stage queue (specs/05's 7 stages) ---

resource "aws_cloudwatch_metric_alarm" "dlq_non_empty" {
  for_each = var.dlq_names

  alarm_name          = "${var.name}-dlq-${each.key}-non-empty"
  alarm_description   = "Dead-letter queue for the '${each.key}' pipeline stage has undelivered jobs — a job failed all 5 redrive attempts and needs manual retriage."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.dlq_message_count_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}

# --- SLO breach (coarse proxy): ALB-level 5xx rate + p95 target response time, per app ---

locals {
  albed_apps = {
    api = var.api_target_group_arn_suffix
    web = var.web_target_group_arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  for_each = local.albed_apps

  alarm_name          = "${var.name}-${each.key}-5xx-rate"
  alarm_description   = "${each.key}: ALB is returning 5xx responses at or above threshold."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.alb_5xx_count_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "alb_p95_latency" {
  for_each = local.albed_apps

  alarm_name          = "${var.name}-${each.key}-p95-latency"
  alarm_description   = "${each.key}: ALB target response time p95 is above threshold — see this alarm's variable docstring for what it does and doesn't prove."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = each.value }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.alb_p95_latency_seconds_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}

# --- ECS service health (not in specs/02's alarm list, but the same free signal for the
# same services already provisioned — see module docstring) ---

locals {
  ecs_services = {
    api    = var.api_service_name
    web    = var.web_service_name
    worker = var.worker_service_name
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  for_each = local.ecs_services

  alarm_name          = "${var.name}-${each.key}-cpu-high"
  alarm_description   = "${each.key} ECS service CPU utilization is above threshold."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  dimensions          = { ClusterName = var.ecs_cluster_name, ServiceName = each.value }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = var.ecs_cpu_high_threshold_percent
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "ecs_memory_high" {
  for_each = local.ecs_services

  alarm_name          = "${var.name}-${each.key}-memory-high"
  alarm_description   = "${each.key} ECS service memory utilization is above threshold."
  namespace           = "AWS/ECS"
  metric_name         = "MemoryUtilization"
  dimensions          = { ClusterName = var.ecs_cluster_name, ServiceName = each.value }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = var.ecs_memory_high_threshold_percent
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}

# --- RLS policy violation attempts + integrity-verifier failure: log-based metric
# filters against app/core/logging.py's JSON lines (see module docstring above) ---

resource "aws_cloudwatch_log_metric_filter" "rls_violation" {
  name           = "${var.name}-rls-violation"
  log_group_name = var.api_log_group_name
  pattern        = "{ $.event = \"rls_violation\" }"

  metric_transformation {
    name      = "RlsViolationCount"
    namespace = "${var.name}/Security"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "rls_violation" {
  alarm_name          = "${var.name}-rls-violation"
  alarm_description   = "A write was blocked by a Row-Level Security policy — either a real cross-tenant attempt or an app bug writing with the wrong org context. Treat as the SEV-1 tenant-isolation bar (docs/on-call-runbook.md §3) until ruled out, not routine noise."
  namespace           = aws_cloudwatch_log_metric_filter.rls_violation.metric_transformation[0].namespace
  metric_name         = aws_cloudwatch_log_metric_filter.rls_violation.metric_transformation[0].name
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.rls_violation_count_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}

resource "aws_cloudwatch_log_metric_filter" "integrity_verifier_failure" {
  name           = "${var.name}-integrity-verifier-failure"
  log_group_name = var.api_log_group_name
  pattern        = "{ $.event = \"export.integrity_failed\" }"

  metric_transformation {
    name      = "IntegrityVerifierFailureCount"
    namespace = "${var.name}/Security"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "integrity_verifier_failure" {
  alarm_name          = "${var.name}-integrity-verifier-failure"
  alarm_description   = "An export was blocked by the integrity verifier (specs/05-redaction-pipeline.md Stage 7) — a redaction didn't burn in cleanly. Not a routine failure: this is the last gate before a document would otherwise leave with recoverable content."
  namespace           = aws_cloudwatch_log_metric_filter.integrity_verifier_failure.metric_transformation[0].namespace
  metric_name         = aws_cloudwatch_log_metric_filter.integrity_verifier_failure.metric_transformation[0].name
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.integrity_verifier_failure_count_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = var.tags
}
