variable "name" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "custom_domain" {
  description = "Optional subdomain (e.g. fleetalert.10finger.dev) to request an ACM cert for."
  type        = string
  default     = null
}

variable "attach_custom_domain" {
  description = "Attach the (already DNS-validated) cert to CloudFront as an alias. Requires custom_domain."
  type        = bool
  default     = false

  validation {
    condition     = !var.attach_custom_domain || var.custom_domain != null
    error_message = "attach_custom_domain requires custom_domain to be set."
  }
}
