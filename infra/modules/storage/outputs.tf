output "bucket_name" {
  value = aws_s3_bucket.content.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.content.arn
}

output "platform_kms_key_arn" {
  value = aws_kms_key.platform.arn
}

output "per_org_kms_management_policy_arn" {
  value = aws_iam_policy.per_org_kms_management.arn
}

output "content_bucket_access_policy_arn" {
  value = aws_iam_policy.content_bucket_access.arn
}
