# The hosted MCP server, a companion to the demo rather than part of it
# (docs/decisions/ADR-0025). Its package is built from the fleetalert-mcp
# repo at a pinned tag by infra/scripts/build_mcp_package.sh before plan
# and apply, the same way the backend package is.
locals {
  mcp_source_dir = "${path.module}/../../../backend/build/mcp_package"
}

module "mcp_server" {
  source                  = "../../modules/mcp_server"
  name                    = "${var.project_name}-demo-mcp"
  source_dir              = local.mcp_source_dir
  fleetalert_api_endpoint = module.api_gateway.api_endpoint
  tier                    = "executes_action"
  tags                    = local.common_tags
}

output "mcp_url" {
  description = "Connect an MCP client here with a token from the tokens secret."
  value       = module.mcp_server.mcp_url
}

output "mcp_tokens_secret_arn" {
  description = "Set its value by hand: {\"tokens\": \"client:tier:secret,...\", \"state_key\": \"<64 hex>\"}."
  value       = module.mcp_server.tokens_secret_arn
}
