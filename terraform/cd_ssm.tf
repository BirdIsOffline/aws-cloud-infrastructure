locals {
  cd_contract = jsondecode(file("${path.module}/../config/ssm/approved-release.json"))
  cd_document_content = replace(replace(
    file("${path.module}/../config/ssm/deploy-server.json"),
    "__EXECUTOR_BASE64__", filebase64("${path.module}/../scripts/ssm/executor.py")
  ), "__CONTRACT_BASE64__", base64encode(jsonencode(local.cd_contract)))
  cd_executor_revision = sha256(local.cd_document_content)
}

resource "aws_ssm_document" "deploy_server" {
  name            = "${local.cd_contract.document_name_prefix}-${local.cd_executor_revision}"
  document_type   = "Command"
  document_format = "JSON"
  target_type     = "/AWS::EC2::Instance"
  content         = local.cd_document_content

  tags = {
    Name             = local.cd_contract.document_name_prefix
    ExecutorRevision = local.cd_executor_revision
  }

  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = length(base64encode(local.cd_document_content)) * 3 / 4 + local.cd_contract.limits.encoded_bytes + 1024 < 60 * 1024
      error_message = "Executor plus maximum parameters must remain below the conservative 60 KiB budget."
    }
    precondition {
      condition     = var.aws_region == "us-east-2"
      error_message = "This executor is reviewed only for the existing us-east-2 lab."
    }
    precondition {
      condition     = !anytrue([for prefix in ["aws", "amazon", "amzn"] : startswith(lower(local.cd_contract.document_name_prefix), prefix)])
      error_message = "Custom SSM document names cannot use AWS-reserved prefixes."
    }
  }
}
