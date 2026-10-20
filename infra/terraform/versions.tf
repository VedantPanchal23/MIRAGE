# ==============================================================================
# MIRAGE 3.0: AWS Private Staging Terraform Version Requirements
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  # For remote state in production, configure S3 backend with DynamoDB locking.
  # For staging preparation, local state is preserved by default.
  # backend "s3" {
  #   bucket         = "mirage-staging-tfstate"
  #   key            = "staging/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "mirage-staging-tflocks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      var.tags,
      {
        Project     = "MIRAGE"
        Environment = var.environment
        ManagedBy   = "Terraform"
      }
    )
  }
}
