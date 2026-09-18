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

output "frontend_url" {
  value = "https://${module.frontend.distribution_domain_name}"
}

output "frontend_bucket_name" {
  value = module.frontend.bucket_name
}

output "frontend_distribution_id" {
  value = module.frontend.distribution_id
}
