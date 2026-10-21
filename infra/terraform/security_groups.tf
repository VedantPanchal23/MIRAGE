# ==============================================================================
# MIRAGE 3.0: Security Groups & Ingress/Egress Controls
# Invariant: Databases, Redis, RabbitMQ, Qdrant, MongoDB, Prometheus, Tempo
# must NEVER be exposed directly to the public internet.
# ==============================================================================

resource "aws_security_group" "staging_host" {
  name        = "mirage-${var.environment}-staging-host-sg"
  description = "Security group for MIRAGE staging host with zero public inbound access"
  vpc_id      = aws_vpc.mirage.id

  # Ingress: Strictly ZERO inbound rules.
  # The host has no open public ports. All administrative, dashboard, and API access
  # is conducted through AWS Systems Manager (SSM) Session Manager and port-forwarding tunnels.
  # Future public showcase access requires an authenticated ALB with ACM TLS termination.

  # Egress: HTTPS for AWS APIs (Secrets Manager, SSM, S3, CloudWatch) and external LLM APIs (Groq, OpenRouter, HF, OpenAI, Anthropic, Gemini)
  egress {
    description = "Allow outbound HTTPS for APIs, packages, and LLM providers"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow outbound HTTP for OS package metadata"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow DNS resolution"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow NTP time synchronization"
    from_port   = 123
    to_port     = 123
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "mirage-${var.environment}-staging-host-sg"
  }
}
