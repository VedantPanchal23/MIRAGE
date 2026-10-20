# ==============================================================================
# MIRAGE 3.0: KMS Customer Managed Key (CMK)
# Enforces encryption at rest with annual automatic key rotation.
# ==============================================================================

resource "aws_kms_key" "mirage" {
  description             = "KMS Customer Managed Key for MIRAGE staging storage and secrets"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name = "mirage-${var.environment}-kms-key"
  }
}

resource "aws_kms_alias" "mirage" {
  name          = "alias/mirage-${var.environment}"
  target_key_id = aws_kms_key.mirage.key_id
}
