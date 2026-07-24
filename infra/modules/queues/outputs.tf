output "queue_urls" {
  value = { for k, q in aws_sqs_queue.this : k => q.url }
}

output "queue_arns" {
  value = { for k, q in aws_sqs_queue.this : k => q.arn }
}

output "dlq_arns" {
  value = { for k, q in aws_sqs_queue.dlq : k => q.arn }
}
