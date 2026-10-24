# The hosted MCP server (docs/decisions/ADR-0025): the fleetalert-mcp package
# from github.com/mbgolden/fleetalert-mcp, run as a Lambda behind its own HTTP
# API. It is a client of the demo API, not part of it -- nothing here touches
# the state machine or the tables.

# The secret VALUE is never set here, same rule as the Anthropic key: Michael
# sets it by hand. Shape:
#   {"tokens": "visitor:read_only:<secret>,ops:executes_action:<secret>",
#    "state_key": "<64 hex chars>"}
resource "aws_secretsmanager_secret" "tokens" {
  name        = "${var.name}-tokens"
  description = "Governor keys and the elicitation state key for the hosted MCP server. Set the value manually -- see infra/README.md."
  tags        = var.tags
}

# Its own API rather than routes on the demo API: the MCP server owns every
# path under its origin (/mcp, /.well-known/..., /healthz, /metrics), and
# MCP clients are not browsers, so no CORS. Created before the function so
# the function's environment can carry the public endpoint without a cycle.
resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
  tags          = var.tags
}

module "lambda" {
  source        = "../lambda_function"
  function_name = var.name
  description   = "fleetalert-mcp: MCP server over the FleetAlert API, stateless JSON mode (ADR-0025)."
  handler       = "fleetalert_mcp.lambda_handler.handler"
  timeout       = 30
  memory_size   = 512
  source_dir    = var.source_dir

  environment = {
    FLEETALERT_MCP_TIER             = var.tier
    FLEETALERT_MCP_PUBLIC_URL       = aws_apigatewayv2_api.this.api_endpoint
    FLEETALERT_MCP_SECRET_ARN       = aws_secretsmanager_secret.tokens.arn
    FLEETALERT_MCP_API_BASE_URL     = var.fleetalert_api_endpoint
    FLEETALERT_MCP_CALLS_PER_MINUTE = tostring(var.calls_per_minute)
    FLEETALERT_MCP_ACTIONS_PER_HOUR = tostring(var.actions_per_hour)
  }

  policy_statements = [
    {
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.tokens.arn]
    },
  ]

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.lambda.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  tags        = var.tags
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
