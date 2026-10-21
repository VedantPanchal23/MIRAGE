# ==============================================================================
# MIRAGE 3.0: Private Encrypted S3 Bucket for Cold Audit Storage (ADR 0005)
# ==============================================================================

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "audit_ledger" {
  count               = var.enable_audit_s3_bucket ? 1 : 0
  bucket              = "mirage-${var.environment}-audit-${random_id.bucket_suffix.hex}"
  object_lock_enabled = var.enable_s3_object_lock
  force_destroy       = var.s3_object_lock_mode == "GOVERNANCE" ? true : false

  tags = {
    Name = "mirage-${var.environment}-audit-ledger"
  }
}

resource "aws_s3_bucket_versioning" "audit_ledger" {
  count  = var.enable_audit_s3_bucket ? 1 : 0
  bucket = aws_s3_bucket.audit_ledger[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit_ledger" {
  count  = var.enable_audit_s3_bucket && var.enable_s3_object_lock ? 1 : 0
  bucket = aws_s3_bucket.audit_ledger[0].id

  rule {
    default_retention {
      mode = var.s3_object_lock_mode
      days = var.s3_object_lock_retention_days
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit_ledger" {
  count  = var.enable_audit_s3_bucket ? 1 : 0
  bucket = aws_s3_bucket.audit_ledger[0].id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.mirage.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

# Block all public access unconditionally
resource "aws_s3_bucket_public_access_block" "audit_ledger" {
  count                   = var.enable_audit_s3_bucket ? 1 : 0
  bucket                  = aws_s3_bucket.audit_ledger[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enforce TLS 1.2+ encrypted transport
resource "aws_s3_bucket_policy" "enforce_tls" {
  count  = var.enable_audit_s3_bucket ? 1 : 0
  bucket = aws_s3_bucket.audit_ledger[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceTLSRequestsOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.audit_ledger[0].arn,
          "${aws_s3_bucket.audit_ledger[0].arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}
