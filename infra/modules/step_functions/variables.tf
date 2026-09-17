variable "name" {
  type = string
}

variable "agent_loop_lambda_arn" {
  type = string
}

variable "wait_for_confirmation_lambda_arn" {
  type = string
}

variable "execute_fix_lambda_arn" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
