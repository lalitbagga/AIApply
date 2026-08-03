terraform {
  backend "s3" {
    bucket         = "aiapply-terraform-state-924029800762"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-locks"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  required_version = ">= 1.5.0"
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "aiapply"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
