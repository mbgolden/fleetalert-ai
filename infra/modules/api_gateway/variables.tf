variable "name" {
  type = string
}

variable "lambda_invoke_arn" {
  type = string
}

variable "lambda_function_name" {
  type = string
}

variable "allowed_origins" {
  description = "Origins the frontend is actually served from -- see docs/decisions/ADR-0007-defer-cors-until-final-domains.md."
  type        = list(string)
}

variable "tags" {
  type    = map(string)
  default = {}
}
