# ==============================================================================
# MIRAGE 3.0: AWS Private Staging Variables
# ==============================================================================

variable "aws_region" {
  type        = string
  description = "Target AWS region for MIRAGE staging deployment"
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Deployment environment name (e.g., staging)"
  default     = "staging"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the dedicated staging VPC"
  default     = "10.50.0.0/16"
}

variable "public_subnet_cidr" {
  type        = string
  description = "CIDR block for the public staging subnet"
  default     = "10.50.1.0/24"
}

variable "private_subnet_cidr" {
  type        = string
  description = "CIDR block for the private staging subnet"
  default     = "10.50.10.0/24"
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type for staging host. Evaluated against 12-container footprint (2.3 CPU res, 3.3 GB RAM res -> min t3.large)"
  default     = "t3.large"
}

variable "volume_size_gb" {
  type        = number
  description = "Root GP3 EBS volume size in GB for container images and persistent volumes"
  default     = 50
}

variable "admin_cidrs" {
  type        = list(string)
  description = "CIDR blocks permitted to access staging HTTPS/SSH. If empty, ingress is disabled (access strictly via AWS SSM Session Manager)"
  default     = []
}

variable "enable_public_edge" {
  type        = bool
  description = "Whether to assign a public IPv4 address to the staging host for direct outbound egress (SSM, Secrets Manager, LLM APIs). When true, security groups strictly enforce zero inbound rules (no public ports). When false, requires enable_vpc_endpoints or NAT Gateway for SSM connectivity"
  default     = true
}

variable "enable_vpc_endpoints" {
  type        = bool
  description = "Provision AWS PrivateLink VPC endpoints for SSM, Secrets Manager, KMS, and S3 Gateway when public edge is disabled"
  default     = false
}

variable "enable_audit_s3_bucket" {
  type        = bool
  description = "Create private S3 bucket with KMS encryption for immutable audit anchor storage (ADR 0005)"
  default     = true
}

variable "enable_s3_object_lock" {
  type        = bool
  description = "Enable S3 Object Lock WORM capability on the audit ledger bucket"
  default     = true
}

variable "s3_object_lock_mode" {
  type        = string
  description = "S3 Object Lock retention mode: GOVERNANCE (allows administrative teardown with bypass permission) or COMPLIANCE (strictly indelible until expiration)"
  default     = "GOVERNANCE"

  validation {
    condition     = contains(["GOVERNANCE", "COMPLIANCE"], var.s3_object_lock_mode)
    error_message = "s3_object_lock_mode must be either GOVERNANCE or COMPLIANCE."
  }
}

variable "s3_object_lock_retention_days" {
  type        = number
  description = "Default retention window in days for audit ledger objects under Object Lock"
  default     = 90
}

variable "tags" {
  type        = map(string)
  description = "Additional resource tags for AWS cost attribution and inventory"
  default     = {}
}
