output "table_names" {
  value = {
    machines       = aws_dynamodb_table.machines.name
    telemetry      = aws_dynamodb_table.telemetry.name
    alerts         = aws_dynamodb_table.alerts.name
    knowledge_base = aws_dynamodb_table.knowledge_base.name
    traces         = aws_dynamodb_table.traces.name
    usage          = aws_dynamodb_table.usage.name
  }
}

output "table_arns" {
  value = {
    machines       = aws_dynamodb_table.machines.arn
    telemetry      = aws_dynamodb_table.telemetry.arn
    alerts         = aws_dynamodb_table.alerts.arn
    knowledge_base = aws_dynamodb_table.knowledge_base.arn
    traces         = aws_dynamodb_table.traces.arn
    usage          = aws_dynamodb_table.usage.arn
  }
}
