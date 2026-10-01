# Dashboard, alarms and an alert topic (docs/decisions/ADR-0017). The
# FleetAlert namespace is written by fleetalert.metrics: every trace span
# becomes CloudWatch Embedded Metric Format data points in the Lambda logs.

locals {
  metrics_namespace = "FleetAlert"
  spend_alarm_usd   = var.daily_cost_cap_usd * 0.8
}

# Subscribe to this topic by hand (console or phone) to get alarm emails;
# no address lives in the repo.
resource "aws_sns_topic" "alarms" {
  name = "${var.project_name}-demo-alarms"
  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "daily_spend" {
  alarm_name          = "${var.project_name}-demo-daily-spend"
  alarm_description   = "Estimated model spend today is at 80% of the daily cap."
  namespace           = local.metrics_namespace
  metric_name         = "InvestigationCostUSD"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = local.spend_alarm_usd
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "budget_exhausted" {
  alarm_name          = "${var.project_name}-demo-budget-exhausted"
  alarm_description   = "The daily cost guard refused an investigation round."
  namespace           = local.metrics_namespace
  metric_name         = "GuardrailBlocks"
  dimensions          = { Guardrail = "guardrail.daily_budget" }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "denied_capability_calls" {
  alarm_name          = "${var.project_name}-demo-denied-capability-calls"
  alarm_description   = "The model asked for a capability outside its safety tier. Should never happen."
  namespace           = local.metrics_namespace
  metric_name         = "CapabilityCalls"
  dimensions          = { Status = "denied" }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "failed_executions" {
  alarm_name          = "${var.project_name}-demo-failed-executions"
  alarm_description   = "An investigation or fix execution failed after all retries."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = module.step_functions.state_machine_arn }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = local.common_tags
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-demo"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 2
        properties = {
          markdown = "## FleetAlert AI\nEvery trace span also becomes a metric (namespace `FleetAlert`). Spend is estimated from token usage; the daily cap is USD ${var.daily_cost_cap_usd} or ${var.daily_investigation_cap} rounds, whichever comes first (ADR-0017)."
        }
      },
      {
        type = "metric", x = 0, y = 2, width = 8, height = 6
        properties = {
          title   = "Investigations by entry point"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = true
          period  = 3600
          metrics = [[{ expression = "SEARCH('{FleetAlert,EntryPoint} MetricName=\"Investigations\"', 'Sum', 3600)", id = "e1" }]]
        }
      },
      {
        type = "metric", x = 8, y = 2, width = 8, height = 6
        properties = {
          title   = "Outcomes"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = true
          period  = 3600
          metrics = [[{ expression = "SEARCH('{FleetAlert,Outcome} MetricName=\"Investigations\"', 'Sum', 3600)", id = "e1" }]]
        }
      },
      {
        type = "metric", x = 16, y = 2, width = 8, height = 6
        properties = {
          title  = "Estimated model spend per day (USD)"
          region = var.aws_region
          view   = "timeSeries"
          period = 86400
          stat   = "Sum"
          metrics = [
            [local.metrics_namespace, "InvestigationCostUSD", { label = "spend" }],
          ]
          annotations = {
            horizontal = [
              { label = "daily cap", value = var.daily_cost_cap_usd },
              { label = "alarm", value = local.spend_alarm_usd },
            ]
          }
        }
      },
      {
        type = "metric", x = 0, y = 8, width = 8, height = 6
        properties = {
          title  = "Investigation latency (ms)"
          region = var.aws_region
          view   = "timeSeries"
          period = 3600
          metrics = [
            [local.metrics_namespace, "InvestigationLatencyMs", { stat = "p50", label = "p50" }],
            [local.metrics_namespace, "InvestigationLatencyMs", { stat = "p90", label = "p90" }],
          ]
        }
      },
      {
        type = "metric", x = 8, y = 8, width = 8, height = 6
        properties = {
          title   = "Capability calls by status"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = true
          period  = 3600
          metrics = [[{ expression = "SEARCH('{FleetAlert,Status} MetricName=\"CapabilityCalls\"', 'Sum', 3600)", id = "e1" }]]
        }
      },
      {
        type = "metric", x = 16, y = 8, width = 8, height = 6
        properties = {
          title  = "Tokens per hour"
          region = var.aws_region
          view   = "timeSeries"
          period = 3600
          stat   = "Sum"
          metrics = [
            [local.metrics_namespace, "InputTokens", { label = "input" }],
            [local.metrics_namespace, "OutputTokens", { label = "output" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 14, width = 8, height = 6
        properties = {
          title   = "Guardrail blocks"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = true
          period  = 3600
          metrics = [[{ expression = "SEARCH('{FleetAlert,Guardrail} MetricName=\"GuardrailBlocks\"', 'Sum', 3600)", id = "e1" }]]
        }
      },
      {
        type = "metric", x = 8, y = 14, width = 8, height = 6
        properties = {
          title   = "Routed to support, by reason"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = true
          period  = 3600
          metrics = [[{ expression = "SEARCH('{FleetAlert,Reason} MetricName=\"RoutedToSupport\"', 'Sum', 3600)", id = "e1" }]]
        }
      },
      {
        type = "metric", x = 16, y = 14, width = 8, height = 6
        properties = {
          title   = "Human actions"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = true
          period  = 3600
          metrics = [[{ expression = "SEARCH('{FleetAlert,Action} MetricName=\"HumanActions\"', 'Sum', 3600)", id = "e1" }]]
        }
      },
      {
        type = "metric", x = 0, y = 26, width = 12, height = 6
        properties = {
          title   = "Telemetry detector runs, by result"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = true
          period  = 3600
          metrics = [[{ expression = "SEARCH('{FleetAlert,Result} MetricName=\"DetectorRuns\"', 'Sum', 3600)", id = "e1" }]]
        }
      },
      {
        type = "metric", x = 0, y = 20, width = 12, height = 6
        properties = {
          title  = "Step Functions executions"
          region = var.aws_region
          view   = "timeSeries"
          period = 3600
          stat   = "Sum"
          metrics = [
            ["AWS/States", "ExecutionsStarted", "StateMachineArn", module.step_functions.state_machine_arn, { label = "started" }],
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", module.step_functions.state_machine_arn, { label = "succeeded" }],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", module.step_functions.state_machine_arn, { label = "failed" }],
            ["AWS/States", "ExecutionsTimedOut", "StateMachineArn", module.step_functions.state_machine_arn, { label = "timed out" }],
          ]
        }
      },
      {
        type = "alarm", x = 12, y = 20, width = 12, height = 6
        properties = {
          title = "Alarms"
          alarms = [
            aws_cloudwatch_metric_alarm.daily_spend.arn,
            aws_cloudwatch_metric_alarm.budget_exhausted.arn,
            aws_cloudwatch_metric_alarm.denied_capability_calls.arn,
            aws_cloudwatch_metric_alarm.failed_executions.arn,
          ]
        }
      },
    ]
  })
}
