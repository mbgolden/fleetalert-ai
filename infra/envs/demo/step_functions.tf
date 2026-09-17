module "step_functions" {
  source                           = "../../modules/step_functions"
  name                             = "${var.project_name}-demo-investigation"
  agent_loop_lambda_arn            = module.lambda_agent_loop.function_arn
  wait_for_confirmation_lambda_arn = module.lambda_wait_for_confirmation.function_arn
  execute_fix_lambda_arn           = module.lambda_execute_fix.function_arn

  tags = local.common_tags
}
