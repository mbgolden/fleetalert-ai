# The secret VALUE is never set here -- Terraform only creates the empty
# entry. Michael sets the actual Anthropic API key by hand (console or
# `aws secretsmanager put-secret-value`); Claude never touches raw key
# material for this project.
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name        = "${var.project_name}-demo-anthropic-api-key"
  description = "Anthropic API key for the FleetAlert AI agent loop. Set the value manually -- see infra/README.md."
  tags = {
    project = var.project_name
    env     = "demo"
  }
}
