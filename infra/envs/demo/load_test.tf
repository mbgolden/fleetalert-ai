# Load-test generator (docs/decisions/ADR-0023). Invoked only by the
# "Load test" GitHub workflow: it creates LT- alerts and starts real
# investigations at a set rate (with a scripted model, so no Claude spend),
# then reports timings from the traces and cleans up.

module "lambda_load_test" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-load-test"
  description   = "Generates load-test investigations, reports their timings, cleans up."
  handler       = "fleetalert.handlers.load_test_handler.handler"
  timeout       = 900
  memory_size   = 512
  source_dir    = local.lambda_source_dir

  environment = merge(local.common_environment, {
    STATE_MACHINE_ARN        = module.step_functions.state_machine_arn
    AGENT_LOOP_FUNCTION_NAME = module.lambda_agent_loop.function_name
  })

  policy_statements = [
    local.dynamodb_read_write_statement,
    {
      effect    = "Allow"
      actions   = ["states:StartExecution"]
      resources = [module.step_functions.state_machine_arn]
    },
    {
      # Read-only metric queries for the report; CloudWatch doesn't support
      # resource-level scoping for GetMetricStatistics.
      effect    = "Allow"
      actions   = ["cloudwatch:GetMetricStatistics"]
      resources = ["*"]
    },
  ]

  tags = local.common_tags
}

output "load_test_function_name" {
  value = module.lambda_load_test.function_name
}
