# The simulated inbound-email entry point (docs/decisions/ADR-0016): every
# 4 hours the seeded email "arrives" and starts an investigation with
# entry_point = "email", through the same state machine as the web UI.
# The demo's "Simulate inbound email" button runs the same code via the API.

module "lambda_email_trigger" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-email-trigger"
  description   = "Delivers the seeded inbound email and starts an email-entry investigation."
  handler       = "fleetalert.handlers.email_trigger_handler.handler"
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
  ]

  tags = local.common_tags
}

resource "aws_cloudwatch_event_rule" "email_schedule" {
  name                = "${var.project_name}-demo-email-schedule"
  description         = "Deliver the simulated inbound email every 4 hours."
  schedule_expression = "rate(4 hours)"
  tags                = local.common_tags
}

resource "aws_cloudwatch_event_target" "email_schedule" {
  rule = aws_cloudwatch_event_rule.email_schedule.name
  arn  = module.lambda_email_trigger.function_arn
}

resource "aws_lambda_permission" "email_schedule" {
  statement_id  = "AllowEventBridgeEmailSchedule"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_email_trigger.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.email_schedule.arn
}
