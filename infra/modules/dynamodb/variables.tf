variable "project_name" {
  type    = string
  default = "fleetalert-ai"
}

variable "environment" {
  type    = string
  default = "demo"
}

variable "tags" {
  type    = map(string)
  default = {}
}
