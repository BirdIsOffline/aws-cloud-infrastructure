locals {
  cd_repository = "BirdIsOffline/aws-cloud-infrastructure"
  cd_subject = format(
    "repo:BirdIsOffline@%s/aws-cloud-infrastructure@%s:ref:refs/heads/main",
    var.github_deployment_identity.owner_id, var.github_deployment_identity.repository_id
  )
  cd_region_condition = { StringEquals = { "aws:RequestedRegion" = var.aws_region } }
  cd_permissions = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "InvokePinnedExecutor"
        Effect    = "Allow"
        Action    = ["ssm:SendCommand"]
        Resource  = [aws_ssm_document.deploy_server.arn]
        Condition = local.cd_region_condition
      },
      {
        Sid      = "TargetOnlyExistingLabInstance"
        Effect   = "Allow"
        Action   = ["ssm:SendCommand"]
        Resource = [aws_instance.web.arn]
        Condition = {
          StringEquals = {
            "aws:RequestedRegion"  = var.aws_region
            "ssm:resourceTag/Name" = "aws-lab-web-01"
          }
        }
      },
      {
        Sid       = "InspectOnlyPinnedExecutor"
        Effect    = "Allow"
        Action    = ["ssm:DescribeDocument"]
        Resource  = [aws_ssm_document.deploy_server.arn]
        Condition = local.cd_region_condition
      },
      {
        Sid    = "NecessaryRegionalReads"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances", "ec2:DescribeVpcs", "ssm:DescribeInstanceInformation",
          "ssm:GetCommandInvocation", "cloudwatch:GetMetricStatistics", "logs:DescribeLogGroups"
        ]
        Resource  = ["*"]
        Condition = local.cd_region_condition
      },
      {
        Sid       = "InspectLabStreamMetadata"
        Effect    = "Allow"
        Action    = ["logs:DescribeLogStreams"]
        Resource  = [for group in aws_cloudwatch_log_group.nginx : "${group.arn}:*"]
        Condition = local.cd_region_condition
      }
    ]
  }
  # Independent explicit ceiling: widening an identity policy cannot add actions.
  cd_boundary_actions = [
    "ssm:SendCommand", "ssm:DescribeDocument", "ssm:DescribeInstanceInformation",
    "ssm:GetCommandInvocation", "ec2:DescribeInstances", "ec2:DescribeVpcs",
    "cloudwatch:GetMetricStatistics", "logs:DescribeLogGroups", "logs:DescribeLogStreams",
    "sts:GetCallerIdentity"
  ]
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # Provider 6.74 supports service-retrieved CA thumbprints on creation.
  # Do not paste historical certificate fingerprints from examples.
  lifecycle { prevent_destroy = true }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "aws-lab-github-deploy-role"
  description          = "Restricted manually authorized GitHub lab server deployment"
  max_session_duration = 3600
  permissions_boundary = aws_iam_policy.github_deploy_boundary.arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud"                 = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub"                 = local.cd_subject
          "token.actions.githubusercontent.com:repository_owner_id" = var.github_deployment_identity.owner_id
          "token.actions.githubusercontent.com:repository_id"       = var.github_deployment_identity.repository_id
          "token.actions.githubusercontent.com:actor_id"            = sort(tolist(var.github_deployment_identity.actor_ids))
          "token.actions.githubusercontent.com:ref"                 = "refs/heads/main"
          "token.actions.githubusercontent.com:workflow"            = "Deploy lab server"
          "token.actions.githubusercontent.com:job_workflow_ref"    = "${local.cd_repository}/.github/workflows/deploy-server-executor.yml@refs/heads/main"
        }
      }
    }]
  })
  lifecycle { prevent_destroy = true }
}

resource "aws_iam_policy" "github_deploy" {
  name        = "aws-lab-github-deploy"
  description = "Invoke one reviewed document on the existing lab instance and inspect results"
  policy      = jsonencode(local.cd_permissions)
}

resource "aws_iam_role_policy_attachment" "github_deploy" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = aws_iam_policy.github_deploy.arn
}

resource "aws_iam_policy" "github_deploy_boundary" {
  name        = "aws-lab-github-deploy-boundary"
  description = "Deployment permission ceiling; no IAM, executor mutation, lifecycle or state access"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.cd_permissions.Statement, [
      { Sid = "DenyOutsideReviewedActionCeiling", Effect = "Deny", NotAction = local.cd_boundary_actions, Resource = "*" },
      {
        Sid         = "DenyOtherTargetsOrExecutors", Effect = "Deny", Action = "ssm:SendCommand"
        NotResource = [aws_instance.web.arn, aws_ssm_document.deploy_server.arn]
      },
      {
        Sid       = "DenyRegionalOperationsElsewhere", Effect = "Deny"
        Action    = ["ssm:*", "ec2:*", "logs:*", "cloudwatch:*"]
        Resource  = "*"
        Condition = { StringNotEquals = { "aws:RequestedRegion" = var.aws_region } }
      }
    ])
  })
  lifecycle { prevent_destroy = true }
}
