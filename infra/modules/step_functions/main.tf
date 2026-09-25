# See docs/decisions/ADR-0001-step-functions-task-token-callback.md for why
# WaitForConfirmation uses the waitForTaskToken service integration instead
# of a DB-flag/polling approach.
#
# Two different "confirmation tokens" are in play here, deliberately kept
# separate:
#   - The Step Functions task token ($$.Task.Token), known only to AWS and
#     to whatever calls SendTaskSuccess/SendTaskFailure. WaitForConfirmation
#     persists it on the alert (as step_functions_task_token) purely so the
#     not-yet-built confirm/reject API handlers can find it later.
#   - fleetalert's own `confirmation_token` (a uuid), set earlier by
#     fleetalert.agent.loop._finalize_proposed_fix and re-checked by
#     execute_fix. That's the value threaded through $.confirmation below --
#     the (future) confirm handler must call SendTaskSuccess with an output
#     payload that includes it, since ExecuteFix has no other way to obtain
#     it from the state machine's own data flow.

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "invoke_lambdas" {
  name = "${var.name}-invoke-lambdas"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = [
          var.agent_loop_lambda_arn,
          var.wait_for_confirmation_lambda_arn,
          var.execute_fix_lambda_arn,
        ]
      }
    ]
  })
}

resource "aws_sfn_state_machine" "this" {
  name     = var.name
  role_arn = aws_iam_role.this.arn
  tags     = var.tags

  definition = jsonencode({
    Comment = "FleetAlert AI investigation state machine"
    StartAt = "RunInvestigation"
    States = {
      RunInvestigation = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.agent_loop_lambda_arn
          "Payload.$"  = "$"
        }
        # Only outcome.$ here -- fix_id is present on the awaiting_confirmation
        # outcome but absent on routed_to_support/rejected/failed, and nothing
        # downstream reads $.investigation.fix_id anyway (ExecuteFix threads
        # fix_id through $.confirmation, from WaitForConfirmation's own
        # payload, not from this state). A ResultSelector that unconditionally
        # requires a key gone from those outcomes previously crashed the
        # execution with an uncatchable JSONPath error on every non-fix path.
        ResultSelector = {
          "outcome.$" = "$.Payload.outcome"
        }
        ResultPath = "$.investigation"
        Next       = "IsAwaitingConfirmation"
        Retry = [
          {
            ErrorEquals     = ["States.ALL"]
            IntervalSeconds = 2
            MaxAttempts     = 6
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "Failed"
          }
        ]
      }

      IsAwaitingConfirmation = {
        Type = "Choice"
        Choices = [
          {
            Variable     = "$.investigation.outcome"
            StringEquals = "awaiting_confirmation"
            Next         = "WaitForConfirmation"
          }
        ]
        Default = "RoutedToSupport"
      }

      WaitForConfirmation = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke.waitForTaskToken"
        Parameters = {
          FunctionName = var.wait_for_confirmation_lambda_arn
          Payload = {
            "alert_id.$"   = "$.alert_id"
            "task_token.$" = "$$.Task.Token"
          }
        }
        ResultPath = "$.confirmation"
        Next       = "ExecuteFix"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "Rejected"
          }
        ]
      }

      ExecuteFix = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.execute_fix_lambda_arn
          Payload = {
            "alert_id.$"           = "$.alert_id"
            "fix_id.$"             = "$.confirmation.fix_id"
            "confirmation_token.$" = "$.confirmation.confirmation_token"
          }
        }
        Next = "Complete"
        Retry = [
          {
            ErrorEquals     = ["States.ALL"]
            IntervalSeconds = 2
            MaxAttempts     = 6
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "Failed"
          }
        ]
      }

      Complete = {
        Type = "Succeed"
      }

      RoutedToSupport = {
        Type = "Succeed"
      }

      Rejected = {
        Type  = "Fail"
        Error = "Rejected"
        Cause = "The proposed fix was rejected, or the confirmation wait failed."
      }

      # Reached only after RunInvestigation or ExecuteFix exhausts its 6
      # retries -- see fleetalert.handlers.agent_loop_handler and
      # execute_fix_handler, which mark the alert's own status "failed"
      # (best-effort) before re-raising, on the *last* attempt only, since
      # each earlier retry re-enters "investigating"/"awaiting_confirmation"
      # first and overwrites it.
      Failed = {
        Type  = "Fail"
        Error = "InvestigationFailed"
        Cause = "The agent loop or fix execution failed after 6 retries."
      }
    }
  })
}
