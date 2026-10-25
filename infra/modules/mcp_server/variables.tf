variable "name" {
  description = "Base name for every resource: the function, its API, the tokens secret."
  type        = string
}

variable "source_dir" {
  description = "Directory holding the installed fleetalert-mcp package (see infra/scripts/build_mcp_package.sh)."
  type        = string
}

variable "fleetalert_api_endpoint" {
  description = "The FleetAlert demo API the MCP server fronts."
  type        = string
}

variable "tier" {
  description = "Highest tier of tool the server registers. Tokens narrow it per client; the published visitor token is read_only."
  type        = string
  default     = "executes_action"
}

variable "calls_per_minute" {
  description = "Per client, every tool. Per Lambda container (ADR-0025)."
  type        = number
  default     = 30
}

variable "actions_per_hour" {
  description = "Per client, tools that spend the demo's budget. Per Lambda container (ADR-0025)."
  type        = number
  default     = 6
}

variable "tags" {
  type    = map(string)
  default = {}
}
