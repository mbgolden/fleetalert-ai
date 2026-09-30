locals {
  # Populated by infra/scripts/build_lambda_package.sh before plan/apply --
  # see that script's header comment for why it must run on Linux.
  lambda_source_dir = "${path.module}/../../../backend/build/lambda_package"

  dynamodb_read_write_statement = {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
    ]
    # Tables plus their indexes (the traces alert index is queried directly).
    resources = concat(
      values(module.dynamodb.table_arns),
      [for arn in values(module.dynamodb.table_arns) : "${arn}/index/*"],
    )
  }

  common_environment = {
    FLEETALERT_ENV                     = "demo"
    LOG_LEVEL                          = "INFO"
    FLEETALERT_DAILY_INVESTIGATION_CAP = tostring(var.daily_investigation_cap)
    FLEETALERT_DAILY_COST_CAP_USD      = tostring(var.daily_cost_cap_usd)
  }

  common_tags = {
    project = var.project_name
    env     = "demo"
  }
}

module "lambda_agent_loop" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-agent-loop"
  description   = "Runs the investigation loop (observe/plan/act via Claude tool calling)."
  handler       = "fleetalert.handlers.agent_loop_handler.handler"
  timeout       = 300
  source_dir    = local.lambda_source_dir

  environment = merge(local.common_environment, {
    ANTHROPIC_SECRET_ARN = aws_secretsmanager_secret.anthropic_api_key.arn
    FLEETALERT_MODEL     = "claude-sonnet-5"
  })

  policy_statements = [
    local.dynamodb_read_write_statement,
    {
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.anthropic_api_key.arn]
    },
  ]

  tags = local.common_tags
}

module "lambda_wait_for_confirmation" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-wait-for-confirmation"
  description   = "Persists the Step Functions task token on the alert while awaiting human confirmation."
  handler       = "fleetalert.handlers.wait_for_confirmation_handler.handler"
  timeout       = 30
  source_dir    = local.lambda_source_dir

  environment       = local.common_environment
  policy_statements = [local.dynamodb_read_write_statement]
  tags              = local.common_tags
}

module "lambda_confirmation_timeout" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-confirmation-timeout"
  description   = "Routes an alert to support when nobody confirms or rejects within the wait timeout."
  handler       = "fleetalert.handlers.confirmation_timeout_handler.handler"
  timeout       = 30
  source_dir    = local.lambda_source_dir

  environment       = local.common_environment
  policy_statements = [local.dynamodb_read_write_statement]
  tags              = local.common_tags
}

module "lambda_execute_fix" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-execute-fix"
  description   = "Re-checks the whitelist and confirmation token, then marks the alert resolved."
  handler       = "fleetalert.handlers.execute_fix_handler.handler"
  timeout       = 30
  source_dir    = local.lambda_source_dir

  environment       = local.common_environment
  policy_statements = [local.dynamodb_read_write_statement]
  tags              = local.common_tags
}
