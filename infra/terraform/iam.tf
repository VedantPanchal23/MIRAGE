# ==============================================================================
# MIRAGE 3.0: IAM Roles & Policies (Least-Privilege Bastionless Access)
# ==============================================================================

resource "aws_iam_role" "staging_host" {
  name = "mirage-${var.environment}-staging-host-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "mirage-${var.environment}-staging-host-role"
  }
}

# Attach AWS Systems Manager standard policy for SSH-less terminal access
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.staging_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Scoped Secrets Manager Policy (Read-Only access to mirage/staging/*)
resource "aws_iam_policy" "secrets_read" {
  name        = "mirage-${var.environment}-secrets-read-policy"
  description = "Allows retrieval of staging secrets from AWS Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [
          aws_secretsmanager_secret.application_secrets.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = [
          aws_kms_key.mirage.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "secrets_read" {
  role       = aws_iam_role.staging_host.name
  policy_arn = aws_iam_policy.secrets_read.arn
}

# Scoped S3 Audit Bucket Policy (Cold Evidence Storage ADR 0005)
resource "aws_iam_policy" "audit_storage" {
  count       = var.enable_audit_s3_bucket ? 1 : 0
  name        = "mirage-${var.environment}-audit-storage-policy"
  description = "Allows upload and retrieval of immutable audit anchor proofs"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.audit_ledger[0].arn,
          "${aws_s3_bucket.audit_ledger[0].arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "audit_storage" {
  count      = var.enable_audit_s3_bucket ? 1 : 0
  role       = aws_iam_role.staging_host.name
  policy_arn = aws_iam_policy.audit_storage[0].arn
}

resource "aws_iam_instance_profile" "staging_host" {
  name = "mirage-${var.environment}-staging-instance-profile"
  role = aws_iam_role.staging_host.name
}
