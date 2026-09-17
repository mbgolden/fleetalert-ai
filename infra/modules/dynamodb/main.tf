resource "aws_dynamodb_table" "machines" {
  name         = "${var.project_name}-${var.environment}-machines"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "machine_id"

  attribute {
    name = "machine_id"
    type = "S"
  }

  tags = var.tags
}

resource "aws_dynamodb_table" "telemetry" {
  name         = "${var.project_name}-${var.environment}-telemetry"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "machine_id"
  range_key    = "timestamp"

  attribute {
    name = "machine_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  tags = var.tags
}

resource "aws_dynamodb_table" "alerts" {
  name         = "${var.project_name}-${var.environment}-alerts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "alert_id"

  attribute {
    name = "alert_id"
    type = "S"
  }

  tags = var.tags
}

resource "aws_dynamodb_table" "knowledge_base" {
  name         = "${var.project_name}-${var.environment}-knowledge-base"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "kb_id"

  attribute {
    name = "kb_id"
    type = "S"
  }

  tags = var.tags
}

# Deviates from the brief's literal `log_id (PK), timestamp (SK)` schema:
# the real access pattern is "get the audit trail for alert X, in order",
# so alert_id is the partition key and timestamp is the sort key. log_id
# is kept as a generated unique attribute on each item, not the key.
resource "aws_dynamodb_table" "audit_log" {
  name         = "${var.project_name}-${var.environment}-audit-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "alert_id"
  range_key    = "timestamp"

  attribute {
    name = "alert_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}
