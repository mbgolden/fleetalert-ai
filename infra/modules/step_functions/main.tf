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
        ResultSelector = {
          "outcome.$" = "$.Payload.outcome"
          "fix_id.$"  = "$.Payload.fix_id"
        }
        ResultPath = "$.investigation"
        Next       = "IsAwaitingConfirmation"
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
    }
  })
}
