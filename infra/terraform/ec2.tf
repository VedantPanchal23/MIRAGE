# ==============================================================================
# MIRAGE 3.0: Staging EC2 Instance & Hardened Bootstrapping
# Security Hardening: IMDSv2 enforced, encrypted EBS, least-privilege IAM profile.
# ==============================================================================

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "staging_host" {
  ami                  = data.aws_ami.al2023.id
  instance_type        = var.instance_type
  subnet_id            = aws_subnet.public.id
  iam_instance_profile = aws_iam_instance_profile.staging_host.name

  vpc_security_group_ids = [
    aws_security_group.staging_host.id
  ]

  associate_public_ip_address = var.enable_public_edge

  root_block_device {
    volume_size           = var.volume_size_gb
    volume_type           = "gp3"
    encrypted             = true
    kms_key_id            = aws_kms_key.mirage.arn
    delete_on_termination = true

    tags = {
      Name = "mirage-${var.environment}-root-ebs"
    }
  }

  # Security Hardening: Enforce IMDSv2 (blocks SSRF credential theft)
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "enabled"
  }

  user_data = <<-EOF
              #!/bin/bash
              set -euo pipefail

              echo "=== Starting MIRAGE Staging Host Setup ==="

              # 1. Update OS & install dependencies
              dnf update -y
              dnf install -y docker git jq

              # 2. Enable & start Docker Engine
              systemctl enable --now docker

              # 3. Install Docker Compose plugin (v2)
              mkdir -p /usr/local/lib/docker/cli-plugins
              curl -SL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64" -o /usr/local/lib/docker/cli-plugins/docker-compose
              chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

              # 4. Create root-only MIRAGE runtime directory
              mkdir -p /opt/mirage
              chmod 700 /opt/mirage
              cd /opt/mirage

              # 5. Bootstrap secret fetcher utility
              cat << 'SECRET_EOF' > /opt/mirage/fetch_secrets.sh
              #!/bin/bash
              set -euo pipefail
              SECRET_JSON=$(aws secretsmanager get-secret-value --region ${var.aws_region} --secret-id ${aws_secretsmanager_secret.application_secrets.id} --query SecretString --output text)
              echo "# Auto-generated MIRAGE staging environment" > /opt/mirage/.env
              echo "$SECRET_JSON" | jq -r 'to_entries[] | "\(.key)=\(.value)"' >> /opt/mirage/.env
              chmod 600 /opt/mirage/.env
              echo "Secrets securely synced from AWS Secrets Manager."
              SECRET_EOF
              chmod 700 /opt/mirage/fetch_secrets.sh

              echo "MIRAGE staging host initialization complete. Connect via AWS Systems Manager."
              EOF

  tags = {
    Name = "mirage-${var.environment}-host"
  }
}
