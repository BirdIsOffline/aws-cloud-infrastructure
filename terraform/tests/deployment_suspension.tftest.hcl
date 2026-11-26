# Offline regression checks: every AWS resource/data source is mocked.
# Mock apply resolves computed references in disposable in-memory test state.
mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::aws:policy/offline-deployment-policy"
    }
  }

  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:us-east-2:aws:offline-alerts"
    }
  }

  override_resource {
    target = aws_iam_policy.github_deploy_boundary
    values = {
      arn = "arn:aws:iam::aws:policy/offline-boundary-policy"
    }
  }
}

variables {
  github_deployment_identity = {
    owner_id      = "1"
    repository_id = "2"
    actor_ids     = ["3"]
  }
}

run "ci_only_deployment_cutoff" {
  command = apply

  assert {
    condition     = issensitive(aws_iam_role.github_deploy.assume_role_policy)
    error_message = "The suspended trust policy must retain its existing sensitive classification."
  }

  assert {
    condition = alltrue([
      for statement in jsondecode(aws_iam_role.github_deploy.assume_role_policy).Statement :
      statement.Effect == "Deny"
    ]) && length(jsondecode(aws_iam_role.github_deploy.assume_role_policy).Statement) > 0
    error_message = "The suspended deployment trust must contain no allow statements."
  }

  assert {
    condition = anytrue([
      for statement in jsondecode(aws_iam_role.github_deploy.assume_role_policy).Statement :
      statement.Effect == "Deny" && statement.Action == "sts:AssumeRoleWithWebIdentity" &&
      statement.Principal.Federated == aws_iam_openid_connect_provider.github.arn &&
      !contains(keys(statement), "Condition")
    ])
    error_message = "Federation must be denied unconditionally for the existing issuer."
  }

  assert {
    condition = anytrue([
      for statement in jsondecode(aws_iam_policy.github_deploy.policy).Statement :
      statement.Effect == "Deny" && statement.Action == "*" && statement.Resource == "*" &&
      !contains(keys(statement), "Condition")
    ])
    error_message = "The existing deployment policy must deny all service permissions for issued sessions."
  }

  assert {
    condition     = aws_iam_role.github_deploy.permissions_boundary == aws_iam_policy.github_deploy_boundary.arn
    error_message = "The dedicated deployment role must retain its permissions boundary."
  }

  assert {
    condition     = jsondecode(aws_iam_role.ec2_ssm.assume_role_policy).Statement[0].Effect == "Allow"
    error_message = "Suspension must not revoke the EC2 service role."
  }

  assert {
    condition     = aws_instance.web.associate_public_ip_address == true
    error_message = "The lifecycle exception must preserve public IPv4 assignment on creation."
  }
}
