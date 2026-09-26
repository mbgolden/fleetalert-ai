variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "fleetalert-ai"
}

variable "frontend_custom_domain" {
  type    = string
  default = "fleetalert.10finger.dev"
}

variable "frontend_attach_custom_domain" {
  type    = bool
  default = false
}
