# Resolve the exact discovered Amazon-owned image, never the latest image.
data "aws_ami" "web" {
  most_recent = false
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = [var.web_ami_name]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

# Resolve the existing AWS-managed EBS key without embedding its account ARN.
data "aws_kms_key" "ebs" {
  key_id = "alias/aws/ebs"
}

resource "aws_instance" "web" {
  ami                         = data.aws_ami.web.id
  instance_type               = "t3.micro"
  availability_zone           = aws_subnet.public["public_1"].availability_zone
  subnet_id                   = aws_subnet.public["public_1"].id
  vpc_security_group_ids      = [aws_security_group.web.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.ec2_ssm.name

  tenancy                              = "default"
  ebs_optimized                        = true
  source_dest_check                    = true
  disable_api_termination              = true
  disable_api_stop                     = false
  instance_initiated_shutdown_behavior = "stop"
  monitoring                           = false
  hibernation                          = false

  # Public IPv4 assignment preserves the original enabled launch setting.
  # Verify with normal refresh while running; provider 6.74.0 marks it ForceNew.
  # See README.md for the stopped-instance caveat. Never remove prevent_destroy
  # to bypass an unexpected replacement proposal.

  # No user data, provisioners, or instance-state resource during adoption.
  # Nginx, website files, and the CloudWatch Agent remain separately managed.
  user_data_replace_on_change = false

  cpu_options {
    core_count       = 1
    threads_per_core = 2
  }

  credit_specification {
    cpu_credits = "standard"
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    http_protocol_ipv6          = "disabled"
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_size           = 8
    volume_type           = "gp3"
    iops                  = 3000
    throughput            = 125
    encrypted             = true
    kms_key_id            = data.aws_kms_key.ebs.arn
    delete_on_termination = true
    tags                  = {}
  }

  tags = {
    Name = "aws-lab-web-01"
  }

  lifecycle {
    prevent_destroy = true
  }
}
