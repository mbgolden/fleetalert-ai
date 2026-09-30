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

# Structured spans (docs/decisions/ADR-0011). One trace per investigation
# round: the table key serves "get this trace", and the alert index serves
# the UI's "every span for this alert, in order" -- span_id is a sortable
# timestamp prefix, so both come back chronologically.
resource "aws_dynamodb_table" "traces" {
  name         = "${var.project_name}-${var.environment}-traces"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "trace_id"
  range_key    = "span_id"

  attribute {
    name = "trace_id"
    type = "S"
  }

  attribute {
    name = "span_id"
    type = "S"
  }

  attribute {
    name = "alert_id"
    type = "S"
  }

  global_secondary_index {
    name            = "alert_id-span_id-index"
    hash_key        = "alert_id"
    range_key       = "span_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}
