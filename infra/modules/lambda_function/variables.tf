variable "function_name" {
  type = string
}

variable "description" {
  type    = string
  default = ""
}

variable "handler" {
  type = string
}

variable "runtime" {
  type    = string
  default = "python3.12"
}

variable "timeout" {
  type    = number
  default = 30
}

variable "memory_size" {
  type    = number
  default = 256
}

variable "source_dir" {
  description = "Directory to zip as the deployment package (see infra/scripts/build_lambda_package.sh)."
  type        = string
}

variable "environment" {
  type    = map(string)
  default = {}
}

variable "policy_statements" {
  description = "Extra IAM statements for this function's role, beyond basic CloudWatch Logs access -- one role per function, least privilege, per the brief's IaC requirement."
  type = list(object({
    effect    = string
    actions   = list(string)
    resources = list(string)
  }))
  default = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
