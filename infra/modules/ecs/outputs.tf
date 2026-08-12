output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

# infra/modules/alerting's rls_violation / export.integrity_failed log-based metric
# filters (app/core/logging.py's JSON lines land here via the awslogs driver) run
# against this log group.
output "api_log_group_name" {
  value = aws_cloudwatch_log_group.api.name
}

output "api_service_name" {
  value = aws_ecs_service.api.name
}

output "web_service_name" {
  value = aws_ecs_service.web.name
}

output "worker_service_name" {
  value = aws_ecs_service.worker.name
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "alb_zone_id" {
  value = aws_lb.this.zone_id
}

# CloudWatch's AWS/ApplicationELB metrics key off these ARN suffixes, not the full ARN —
# infra/modules/alerting needs them for the SLO-breach (5xx rate, p95 latency) alarms.
output "alb_arn_suffix" {
  value = aws_lb.this.arn_suffix
}

output "api_target_group_arn_suffix" {
  value = aws_lb_target_group.api.arn_suffix
}

output "web_target_group_arn_suffix" {
  value = aws_lb_target_group.web.arn_suffix
}

output "app_security_group_id" {
  value = aws_security_group.app.id
}

output "task_role_name" {
  value = aws_iam_role.task.name
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}
