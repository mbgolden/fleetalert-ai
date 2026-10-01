variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "fleetalert-ai"
}

variable "daily_investigation_cap" {
  description = "Investigation rounds per UTC day across all entry points (ADR-0017)."
  type        = number
  default     = 50
}

variable "daily_cost_cap_usd" {
  description = "Estimated model spend per UTC day before new rounds are refused (ADR-0017)."
  type        = number
  default     = 1.25
}

variable "investigation_worker_concurrency" {
  description = "Queued investigations run at once (ADR-0024). The account limit is 1,000; the cap bounds concurrent model calls, not Lambda slots."
  type        = number
  default     = 50
}

variable "frontend_custom_domain" {
  type    = string
  default = "fleetalert.10finger.dev"
}

variable "frontend_attach_custom_domain" {
  type    = bool
  default = true
}
