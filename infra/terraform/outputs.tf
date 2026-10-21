# ==============================================================================
# MIRAGE 3.0: Staging Outputs & Operational Entrypoints
# ==============================================================================

output "instance_id" {
  description = "EC2 Instance ID of the staging host"
  value       = aws_instance.staging_host.id
}

output "instance_private_ip" {
  description = "Private IP address of the staging host"
  value       = aws_instance.staging_host.private_ip
}

output "instance_public_ip" {
  description = "Public IPv4 address of the staging host (if public edge is enabled)"
  value       = var.enable_public_edge ? aws_instance.staging_host.public_ip : null
}

output "ssm_connect_command" {
  description = "AWS CLI command to open an encrypted interactive terminal via Systems Manager"
  value       = "aws ssm start-session --target ${aws_instance.staging_host.id} --region ${var.aws_region}"
}

output "secrets_manager_secret_arn" {
  description = "ARN of the Secrets Manager secret for staging credentials"
  value       = aws_secretsmanager_secret.application_secrets.arn
}

output "audit_s3_bucket_name" {
  description = "Name of the private KMS-encrypted S3 audit bucket"
  value       = var.enable_audit_s3_bucket ? aws_s3_bucket.audit_ledger[0].id : null
}

output "audit_bucket_id" {
  description = "Bucket ID / name of the S3 audit bucket"
  value       = var.enable_audit_s3_bucket ? aws_s3_bucket.audit_ledger[0].id : null
}

output "kms_key_arn" {
  description = "ARN of the Customer Managed KMS Key"
  value       = aws_kms_key.mirage.arn
}
