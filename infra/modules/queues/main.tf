# One queue + DLQ per pipeline stage (specs/05-redaction-pipeline.md's 7 stages map to
# these job types; specs/03-data-model.md processing_jobs.type). Workers set org context
# from the message body — never trust a payload-derived path (specs/02-architecture.md
# § Request lifecycle) — so queues carry no server-side per-org isolation of their own;
# that's enforced in the message contract + RLS on write, not at the queue level.

locals {
  queue_types = ["intake", "extract", "detect", "export", "verify", "rule_extraction"]
}

resource "aws_sqs_queue" "dlq" {
  for_each                  = toset(local.queue_types)
  name                      = "${var.name}-${each.key}-dlq"
  message_retention_seconds = 1209600 # 14 days — max time to notice + retriage a DLQ'd job
  kms_master_key_id         = "alias/aws/sqs"
  tags                      = var.tags
}

resource "aws_sqs_queue" "this" {
  for_each                   = toset(local.queue_types)
  name                       = "${var.name}-${each.key}"
  visibility_timeout_seconds = var.visibility_timeout_seconds[each.key]
  message_retention_seconds  = 345600 # 4 days
  kms_master_key_id          = "alias/aws/sqs"

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = 5
  })

  tags = var.tags
}
