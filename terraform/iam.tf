data "aws_partition" "current" {}

resource "aws_iam_role" "ec2_ssm" {
  name                 = "aws-lab-ec2-ssm-role"
  path                 = "/"
  description          = "Allows AWS lab EC2 instances to connect through Systems Manager"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })

  # Preserve the untagged role with no permissions boundary or inline policies.
  # Managed policy attachments are owned only by the standalone resources below.
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2_ssm.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch_agent" {
  role       = aws_iam_role.ec2_ssm.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "ec2_ssm" {
  name = "aws-lab-ec2-ssm-role"
  path = "/"
  role = aws_iam_role.ec2_ssm.name
}
