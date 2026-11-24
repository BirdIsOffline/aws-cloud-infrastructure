data "aws_caller_identity" "current" {}

resource "aws_sns_topic" "alerts" {
  name         = "aws-lab-alerts"
  display_name = ""
  fifo_topic   = false
  tags         = {}

  # No inline policy: aws_sns_topic_policy.alerts is the sole policy owner.
  # Preserve the absence of a configured KMS key and custom delivery policy.
  # The confirmed email subscription is externally managed; do not import it.
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn

  # Preserve the discovered default policy without expanding or narrowing access.
  policy = jsonencode({
    Version = "2008-10-17"
    Id      = "__default_policy_ID"
    Statement = [{
      Sid    = "__default_statement_ID"
      Effect = "Allow"
      Principal = {
        AWS = "*"
      }
      Action = [
        "SNS:GetTopicAttributes",
        "SNS:SetTopicAttributes",
        "SNS:AddPermission",
        "SNS:RemovePermission",
        "SNS:DeleteTopic",
        "SNS:Subscribe",
        "SNS:ListSubscriptionsByTopic",
        "SNS:Publish"
      ]
      Resource = aws_sns_topic.alerts.arn
      Condition = {
        StringEquals = {
          "AWS:SourceOwner" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })
}
