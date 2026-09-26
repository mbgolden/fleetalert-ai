module "lambda_api" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-api"
  description   = "API Gateway handler: list/investigate/status/confirm/reject/audit routes."
  handler       = "fleetalert.handlers.api_handler.handler"
  timeout       = 30
  source_dir    = local.lambda_source_dir

  environment = merge(local.common_environment, {
    STATE_MACHINE_ARN = module.step_functions.state_machine_arn
  })

  policy_statements = [
    local.dynamodb_read_write_statement,
    {
      effect    = "Allow"
      actions   = ["states:StartExecution"]
      resources = [module.step_functions.state_machine_arn]
    },
    {
      # SendTaskSuccess/SendTaskFailure act on an opaque task token, not a
      # state machine ARN -- AWS does not support resource-level scoping
      # for these two actions at all.
      effect    = "Allow"
      actions   = ["states:SendTaskSuccess", "states:SendTaskFailure"]
      resources = ["*"]
    },
  ]

  tags = local.common_tags
}

module "api_gateway" {
  source               = "../../modules/api_gateway"
  name                 = "${var.project_name}-demo-api"
  lambda_invoke_arn    = module.lambda_api.invoke_arn
  lambda_function_name = module.lambda_api.function_name

  # See docs/decisions/ADR-0007-defer-cors-until-final-domains.md --
  # localhost is a deliberate, explicit addition for local dev against
  # the real API, not an accidental side effect of a wildcard.
  allowed_origins = concat(
    [
      "https://${module.frontend.distribution_domain_name}",
      "http://localhost:5173",
    ],
    var.frontend_custom_domain != null ? ["https://${var.frontend_custom_domain}"] : [],
  )

  tags = local.common_tags
}
