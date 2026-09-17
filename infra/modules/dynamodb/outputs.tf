output "table_names" {
  value = {
    machines       = aws_dynamodb_table.machines.name
    telemetry      = aws_dynamodb_table.telemetry.name
    alerts         = aws_dynamodb_table.alerts.name
    knowledge_base = aws_dynamodb_table.knowledge_base.name
    audit_log      = aws_dynamodb_table.audit_log.name
  }
}

output "table_arns" {
  value = {
    machines       = aws_dynamodb_table.machines.arn
    telemetry      = aws_dynamodb_table.telemetry.arn
    alerts         = aws_dynamodb_table.alerts.arn
    knowledge_base = aws_dynamodb_table.knowledge_base.arn
    audit_log      = aws_dynamodb_table.audit_log.arn
  }
}
