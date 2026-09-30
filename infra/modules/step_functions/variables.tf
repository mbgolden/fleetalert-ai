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

variable "confirmation_timeout_lambda_arn" {
  type = string
}

variable "confirmation_timeout_seconds" {
  description = "How long WaitForConfirmation waits for a human before routing to support."
  type        = number
  default     = 7200
}

variable "tags" {
  type    = map(string)
  default = {}
}
