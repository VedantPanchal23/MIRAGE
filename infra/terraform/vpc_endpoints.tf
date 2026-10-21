# ==============================================================================
# MIRAGE 3.0: PrivateLink VPC Endpoints & S3 Gateway Endpoint
# Provides private, internal AWS connectivity for SSM, Secrets Manager, KMS,
# and S3 when the staging host operates without a public IPv4 address.
# ==============================================================================

locals {
  create_vpc_endpoints = !var.enable_public_edge && var.enable_vpc_endpoints
}

# 1. S3 Gateway Endpoint (Always cost-free in AWS)
resource "aws_vpc_endpoint" "s3" {
  count             = var.enable_audit_s3_bucket && (var.enable_vpc_endpoints || !var.enable_public_edge) ? 1 : 0
  vpc_id            = aws_vpc.mirage.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"

  route_table_ids = [
    aws_route_table.public.id
  ]

  tags = {
    Name = "mirage-${var.environment}-s3-gw-endpoint"
  }
}

# 2. Security Group for VPC Interface Endpoints
resource "aws_security_group" "vpc_endpoints" {
  count       = local.create_vpc_endpoints ? 1 : 0
  name        = "mirage-${var.environment}-vpce-sg"
  description = "Security group for PrivateLink interface endpoints"
  vpc_id      = aws_vpc.mirage.id

  ingress {
    description = "Allow inbound HTTPS from staging VPC CIDR"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "mirage-${var.environment}-vpce-sg"
  }
}

# 3. AWS Systems Manager (SSM) Interface Endpoints
resource "aws_vpc_endpoint" "ssm" {
  count               = local.create_vpc_endpoints ? 1 : 0
  vpc_id              = aws_vpc.mirage.id
  service_name        = "com.amazonaws.${var.aws_region}.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.public.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "mirage-${var.environment}-ssm-endpoint"
  }
}

resource "aws_vpc_endpoint" "ssmmessages" {
  count               = local.create_vpc_endpoints ? 1 : 0
  vpc_id              = aws_vpc.mirage.id
  service_name        = "com.amazonaws.${var.aws_region}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.public.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "mirage-${var.environment}-ssmmessages-endpoint"
  }
}

resource "aws_vpc_endpoint" "ec2messages" {
  count               = local.create_vpc_endpoints ? 1 : 0
  vpc_id              = aws_vpc.mirage.id
  service_name        = "com.amazonaws.${var.aws_region}.ec2messages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.public.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "mirage-${var.environment}-ec2messages-endpoint"
  }
}

# 4. AWS Secrets Manager Interface Endpoint
resource "aws_vpc_endpoint" "secretsmanager" {
  count               = local.create_vpc_endpoints ? 1 : 0
  vpc_id              = aws_vpc.mirage.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.public.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "mirage-${var.environment}-secretsmanager-endpoint"
  }
}

# 5. AWS KMS Interface Endpoint
resource "aws_vpc_endpoint" "kms" {
  count               = local.create_vpc_endpoints ? 1 : 0
  vpc_id              = aws_vpc.mirage.id
  service_name        = "com.amazonaws.${var.aws_region}.kms"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.public.id]
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "mirage-${var.environment}-kms-endpoint"
  }
}

# Check block to ensure safety of network mode configuration
check "network_mode_safety" {
  assert {
    condition     = var.enable_public_edge || var.enable_vpc_endpoints
    error_message = "When enable_public_edge is false (no public IPv4 assigned), enable_vpc_endpoints must be set to true to enable AWS SSM Session Manager, Secrets Manager, and KMS connectivity via PrivateLink."
  }
}
