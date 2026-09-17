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

  # Remote state (S3 backend + DynamoDB lock table) added once the AWS
  # account and those resources actually exist — see infra/README.md.
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
