# The autonomous entry point (docs/decisions/ADR-0020): every 4 hours the
# detector generates the monitored truck's last 3 hours of telemetry, checks
# it against threshold rules, and starts an investigation with
# entry_point = "autonomous" if one trips. Normal readings cost nothing.
# The demo's "Run telemetry detector" button runs the same code via the API.

module "lambda_autonomous_detector" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-autonomous-detector"
  description   = "Generates synthetic telemetry, runs the rule-based detector, starts autonomous investigations."
  handler       = "fleetalert.handlers.autonomous_detector_handler.handler"
  timeout       = 30
  source_dir    = local.lambda_source_dir

  environment = merge(local.common_environment, local.enqueue_environment)

  policy_statements = [
    local.dynamodb_read_write_statement,
    local.enqueue_statement,
  ]

  tags = local.common_tags
}

resource "aws_cloudwatch_event_rule" "detector_schedule" {
  name                = "${var.project_name}-demo-detector-schedule"
  description         = "Run the telemetry detector every 4 hours."
  schedule_expression = "rate(4 hours)"
  tags                = local.common_tags
}

resource "aws_cloudwatch_event_target" "detector_schedule" {
  rule = aws_cloudwatch_event_rule.detector_schedule.name
  arn  = module.lambda_autonomous_detector.function_arn
}

resource "aws_lambda_permission" "detector_schedule" {
  statement_id  = "AllowEventBridgeDetectorSchedule"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_autonomous_detector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.detector_schedule.arn
}
