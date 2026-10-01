# Backpressure for machine-generated alerts (docs/decisions/ADR-0024).
# Inbound email, the telemetry detector and load tests put investigation
# requests on this queue. The worker takes them off with a fixed maximum
# concurrency, so a burst waits in the queue instead of exhausting the
# account's Lambda concurrency (which throttled the public API and lost
# 16% of investigations in the load test that prompted this).

resource "aws_sqs_queue" "investigations_dlq" {
  name                      = "${var.project_name}-demo-investigations-dlq"
  message_retention_seconds = 1209600 # 14 days, to leave time to look
  tags                      = local.common_tags
}

resource "aws_sqs_queue" "investigations" {
  name = "${var.project_name}-demo-investigations"
  # At least 6x the worker's timeout, per the Lambda/SQS guidance, so a
  # message isn't redelivered while a slow round is still running.
  visibility_timeout_seconds = 1080
  message_retention_seconds  = 345600 # 4 days
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.investigations_dlq.arn
    maxReceiveCount     = 3
  })
  tags = local.common_tags
}

module "lambda_investigation_worker" {
  source        = "../../modules/lambda_function"
  function_name = "${var.project_name}-demo-investigation-worker"
  description   = "Runs queued investigations at a fixed concurrency; starts the confirmation wait when a human is needed."
  handler       = "fleetalert.handlers.investigation_worker_handler.handler"
  timeout       = 180
  source_dir    = local.lambda_source_dir

  environment = merge(local.common_environment, {
    ANTHROPIC_SECRET_ARN = aws_secretsmanager_secret.anthropic_api_key.arn
    FLEETALERT_MODEL     = "claude-sonnet-5-5"
    STATE_MACHINE_ARN    = module.step_functions.state_machine_arn
  })

  policy_statements = [
    local.dynamodb_read_write_statement,
    {
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.anthropic_api_key.arn]
    },
    {
      effect    = "Allow"
      actions   = ["states:StartExecution"]
      resources = [module.step_functions.state_machine_arn]
    },
    {
      effect    = "Allow"
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      resources = [aws_sqs_queue.investigations.arn]
    },
  ]

  tags = local.common_tags
}

resource "aws_lambda_event_source_mapping" "investigations" {
  event_source_arn        = aws_sqs_queue.investigations.arn
  function_name           = module.lambda_investigation_worker.function_arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]

  # The backpressure control. The account allows 10 concurrent Lambdas in
  # total (too few for AWS to permit reserved concurrency), so the queue's
  # own cap is what leaves room for the API and the web path.
  scaling_config {
    maximum_concurrency = var.investigation_worker_concurrency
  }
}

resource "aws_cloudwatch_metric_alarm" "dead_letters" {
  alarm_name          = "${var.project_name}-demo-investigation-dead-letters"
  alarm_description   = "An investigation request failed three times and was moved to the dead-letter queue."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.investigations_dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "queue_backlog" {
  alarm_name          = "${var.project_name}-demo-investigation-backlog"
  alarm_description   = "The oldest queued investigation has been waiting more than 10 minutes."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.investigations.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 600
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = local.common_tags
}

locals {
  # For the Lambdas that put requests on the queue.
  enqueue_environment = { INVESTIGATION_QUEUE_URL = aws_sqs_queue.investigations.url }
  enqueue_statement = {
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.investigations.arn]
  }
}

output "investigation_queue_url" {
  value = aws_sqs_queue.investigations.url
}
