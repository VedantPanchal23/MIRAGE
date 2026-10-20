# ==============================================================================
# MIRAGE 3.0: Staging VPC & Network Topology
# Cost-conscious architecture: Avoids unnecessary NAT Gateways ($32/mo/AZ)
# ==============================================================================

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "mirage" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "mirage-${var.environment}-vpc"
  }
}

resource "aws_internet_gateway" "mirage" {
  vpc_id = aws_vpc.mirage.id

  tags = {
    Name = "mirage-${var.environment}-igw"
  }
}

# Public Subnet (Hosts staging EC2 with SSM & egress for upstream LLM APIs)
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.mirage.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = var.enable_public_edge

  tags = {
    Name = "mirage-${var.environment}-public-subnet"
    Tier = "Public"
  }
}

# Private Subnet (Reserved for future RDS/ElastiCache managed migrations)
resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.mirage.id
  cidr_block        = var.private_subnet_cidr
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = {
    Name = "mirage-${var.environment}-private-subnet"
    Tier = "Private"
  }
}

# Route table for public subnet
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.mirage.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.mirage.id
  }

  tags = {
    Name = "mirage-${var.environment}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
