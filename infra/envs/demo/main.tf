terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Bucket/table created once by infra/bootstrap -- see that config's
  # header comment for why these names are hardcoded here rather than
  # piped in from a data source (this backend block can't reference
  # variables or other resources at all -- Terraform evaluates it before
  # anything else).
  backend "s3" {
    bucket         = "fleetalert-ai-terraform-state"
    key            = "demo/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "fleetalert-ai-terraform-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

module "dynamodb" {
  source       = "../../modules/dynamodb"
  project_name = var.project_name
  environment  = "demo"
  tags = {
    project = var.project_name
    env     = "demo"
  }
}
