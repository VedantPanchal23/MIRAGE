# ==============================================================================
# MIRAGE 3.0: AWS Secrets Manager (KMS Encrypted Secret Storage)
# Security Invariant: Real secret values are NEVER hardcoded in Terraform.
# Operators populate secrets via AWS Console or AWS CLI after creation.
# ==============================================================================

resource "aws_secretsmanager_secret" "application_secrets" {
  name                    = "mirage/${var.environment}/application_secrets"
  description             = "Encrypted runtime secrets and credentials for MIRAGE staging"
  kms_key_id              = aws_kms_key.mirage.arn
  recovery_window_in_days = 0 # Immediate purge on destroy during staging teardown

  tags = {
    Name = "mirage-${var.environment}-secrets"
  }
}

# Initial schema template (contains placeholder keys, safe for version control)
resource "aws_secretsmanager_secret_version" "initial_template" {
  secret_id = aws_secretsmanager_secret.application_secrets.id
  secret_string = jsonencode({
    SECRET_KEY                 = "REPLACE_WITH_MIN_48_CHAR_SECRET_BEFORE_LAUNCH"
    POSTGRES_PASSWORD          = "REPLACE_WITH_STRONG_DB_ADMIN_PASSWORD"
    POSTGRES_APP_PASSWORD      = "REPLACE_WITH_STRONG_DB_APP_PASSWORD"
    REDIS_PASSWORD             = "REPLACE_WITH_STRONG_REDIS_PASSWORD"
    RABBITMQ_PASSWORD          = "REPLACE_WITH_STRONG_RABBITMQ_PASSWORD"
    CELERY_REDIS_PASSWORD      = "REPLACE_WITH_STRONG_CELERY_REDIS_PASSWORD"
    MONGO_INITDB_ROOT_PASSWORD = "REPLACE_WITH_STRONG_MONGO_ROOT_PASSWORD"
    MONGO_APP_PASSWORD         = "REPLACE_WITH_STRONG_MONGO_APP_PASSWORD"
    QDRANT_API_KEY             = "REPLACE_WITH_STRONG_QDRANT_KEY"
    GRAFANA_ADMIN_PASSWORD     = "REPLACE_WITH_STRONG_GRAFANA_PASSWORD"
    GROQ_API_KEY               = ""
    OPENROUTER_API_KEY         = ""
    HUGGINGFACE_API_KEY        = ""
    OPENAI_API_KEY             = ""
    ANTHROPIC_API_KEY          = ""
    GEMINI_API_KEY             = ""
  })

  lifecycle {
    ignore_changes = [
      secret_string
    ]
  }
}
