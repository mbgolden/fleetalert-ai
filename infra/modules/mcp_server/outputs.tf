output "endpoint" {
  description = "The API's base URL; /healthz and /metrics live here."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "mcp_url" {
  description = "What an MCP client connects to."
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/mcp"
}

output "tokens_secret_arn" {
  value = aws_secretsmanager_secret.tokens.arn
}

output "function_name" {
  value = module.lambda.function_name
}
