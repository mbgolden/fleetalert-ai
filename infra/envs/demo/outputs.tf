output "dynamodb_table_names" {
  value = module.dynamodb.table_names
}

output "state_machine_arn" {
  value = module.step_functions.state_machine_arn
}

output "anthropic_secret_arn" {
  value = aws_secretsmanager_secret.anthropic_api_key.arn
}

output "api_endpoint" {
  value = module.api_gateway.api_endpoint
}
