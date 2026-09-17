# One-time bootstrap for Terraform remote state (S3 bucket + DynamoDB lock
# table), run via .github/workflows/terraform-apply-bootstrap.yml.
#
# This config deliberately does NOT use its own output as a backend for
# itself -- that's the chicken-and-egg problem remote-state bootstrapping
# always has. It's applied once with local state (which only exists for
# the lifetime of that one GitHub Actions run and is then discarded); after
# that, infra/envs/demo points its own backend at the bucket/table created
# here, using their hardcoded names, and everything from that point on is
# managed under the real remote backend. See
# docs/decisions/ADR-0005-terraform-apply-via-gated-github-environment.md.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = "${var.project_name}-terraform-state"
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_dynamodb_table" "terraform_lock" {
  name         = "${var.project_name}-terraform-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
