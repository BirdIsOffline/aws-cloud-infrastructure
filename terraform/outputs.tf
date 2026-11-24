output "vpc_id" {
  description = "Lab VPC ID for resources that join this network."
  value       = aws_vpc.lab.id
}

output "vpc_cidr_block" {
  description = "IPv4 CIDR block of the lab VPC."
  value       = aws_vpc.lab.cidr_block
}

output "public_subnets" {
  description = "Public subnet IDs, CIDRs, names, and Availability Zones by stable key."
  value = {
    for key, subnet in aws_subnet.public : key => {
      id                = subnet.id
      name              = subnet.tags["Name"]
      cidr_block        = subnet.cidr_block
      availability_zone = subnet.availability_zone
    }
  }
}

output "private_subnets" {
  description = "Private subnet IDs, CIDRs, names, and Availability Zones by stable key."
  value = {
    for key, subnet in aws_subnet.private : key => {
      id                = subnet.id
      name              = subnet.tags["Name"]
      cidr_block        = subnet.cidr_block
      availability_zone = subnet.availability_zone
    }
  }
}

output "internet_gateway_id" {
  description = "ID of the internet gateway attached to the lab VPC."
  value       = aws_internet_gateway.lab.id
}

output "route_table_ids" {
  description = "IDs of the two explicitly managed subnet route tables."
  value = {
    public  = aws_route_table.public.id
    private = aws_route_table.private.id
  }
}

output "web_security_group_id" {
  description = "Web security group ID for the later EC2 adoption phase."
  value       = aws_security_group.web.id
}

output "web_instance_id" {
  description = "Web instance ID, resolved after the approved EC2 import."
  value       = aws_instance.web.id
}

output "web_instance_public_ipv4" {
  description = "Automatic public IPv4 address; may be empty while stopped and can change after a stop/start."
  value       = aws_instance.web.public_ip
}

output "ec2_iam_role_name" {
  description = "Name of the EC2 role with Systems Manager and CloudWatch Agent permissions."
  value       = aws_iam_role.ec2_ssm.name
}

output "ec2_instance_profile_name" {
  description = "Name of the instance profile associated with the web instance."
  value       = aws_iam_instance_profile.ec2_ssm.name
}

output "monitoring_dashboard_name" {
  description = "Name of the existing infrastructure monitoring dashboard."
  value       = aws_cloudwatch_dashboard.infrastructure.dashboard_name
}

output "high_cpu_alarm_name" {
  description = "Name of the EC2 CPU alarm connected to the alerts topic."
  value       = aws_cloudwatch_metric_alarm.high_cpu.alarm_name
}

output "alerts_topic_arn" {
  description = "Alerts topic ARN, resolved after the separately approved import."
  value       = aws_sns_topic.alerts.arn
}

output "nginx_log_group_names" {
  description = "Existing Nginx log group names by stable access/error key."
  value = {
    for key, group in aws_cloudwatch_log_group.nginx : key => group.name
  }
}
