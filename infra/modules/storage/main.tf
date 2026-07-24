# Content bucket + the platform's default KMS key.
#
# specs/02-architecture.md ADR-2 / specs/08-security-compliance.md: per-ORG KMS CMKs
# provide cryptographic tenant isolation for document content — those are created and
# rotated at RUNTIME by the API (one per org, via kms:CreateKey), not by this static
# environment stack; see the IAM policy below which grants exactly that ability and
# nothing broader. This module's own KMS key is the platform default — used for the
# bucket's default encryption (defense-in-depth for any object briefly written before an
# org-specific key is attached) and for anything not org-scoped.

resource "aws_kms_key" "platform" {
  description             = "${var.name} platform default CMK (per-org CMKs are created at runtime)"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = var.tags
}

resource "aws_kms_alias" "platform" {
  name          = "alias/${var.name}-platform"
  target_key_id = aws_kms_key.platform.key_id
}

resource "aws_s3_bucket" "content" {
  bucket = "${var.name}-content"
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "content" {
  bucket = aws_s3_bucket.content.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "content" {
  bucket = aws_s3_bucket.content.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.platform.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "content" {
  bucket                  = aws_s3_bucket.content.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Deny any non-TLS request outright (specs/08-security-compliance.md: TLS 1.2+ everywhere).
resource "aws_s3_bucket_policy" "content" {
  bucket = aws_s3_bucket.content.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.content.arn,
          "${aws_s3_bucket.content.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

# Lets the API/workers create + manage per-org CMKs at runtime (specs/08-security-compliance.md:
# per-org CMK, crypto-shred on org offboarding) without granting broader KMS admin rights.
resource "aws_iam_policy" "per_org_kms_management" {
  name        = "${var.name}-per-org-kms-management"
  description = "Runtime per-org CMK create/schedule-deletion for ${var.name} (see specs/08-security-compliance.md)"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CreateAndManagePerOrgKeys"
        Effect = "Allow"
        Action = [
          "kms:CreateKey",
          "kms:CreateAlias",
          "kms:DeleteAlias",
          "kms:ScheduleKeyDeletion",
          "kms:EnableKeyRotation",
          "kms:TagResource",
          "kms:DescribeKey",
          "kms:GetKeyPolicy",
        ]
        Resource = "*"
      },
      {
        # Callers must address the key by its `alias/org-<org_id>` alias (assigned at
        # creation above), not by key ID/ARN directly — `kms:RequestAlias` is the
        # documented AWS global condition key for this (aws.amazon.com/kms docs,
        # "kms:RequestAlias"), scoping crypto ops to per-org keys without needing to
        # enumerate key ARNs that don't exist yet at plan time.
        Sid    = "UseKeysForContent"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey*",
          "kms:ReEncrypt*",
        ]
        Resource = "*"
        Condition = {
          StringLike = { "kms:RequestAlias" = "alias/org-*" }
        }
      },
    ]
  })
}
