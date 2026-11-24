locals {
  # Static keys remain known before either log group is imported.
  nginx_log_groups = {
    access = "/aws/portfolio-lab/nginx/access"
    error  = "/aws/portfolio-lab/nginx/error"
  }
}

resource "aws_cloudwatch_log_group" "nginx" {
  for_each = local.nginx_log_groups

  name                        = each.value
  retention_in_days           = 7
  log_group_class             = "STANDARD"
  deletion_protection_enabled = false
  tags                        = {}

  # Preserve service-managed encryption; no customer KMS key was associated.
  # Agent-created streams and log events remain outside Terraform management.
}

resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "aws-lab-high-cpu-alarm"
  alarm_description   = "Alerts when EC2 CPU utilization reaches 80% or higher for two consecutive 5-minute periods."
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 80
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"
  actions_enabled     = true

  dimensions = {
    InstanceId = aws_instance.web.id
  }

  alarm_actions             = [aws_sns_topic.alerts.arn]
  ok_actions                = []
  insufficient_data_actions = []
  tags                      = {}

  # Unit was not explicitly configured. Alarm runtime state is service-managed.
}

resource "aws_cloudwatch_dashboard" "infrastructure" {
  dashboard_name = "AWSPortfolioInfrastructureMonitoring4"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 6
        height = 6
        properties = {
          metrics = [
            ["AWS/EC2", "CPUUtilization", "InstanceId", aws_instance.web.id, { yAxis = "left" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          stat    = "Average"
          period  = 300
          title   = "EC2 CPU Utilization"
        }
      },
      {
        type   = "metric"
        x      = 6
        y      = 0
        width  = 6
        height = 6
        properties = {
          metrics = [
            ["AWSPortfolioLab", "mem_used_percent", "InstanceId", aws_instance.web.id, { label = "mem_used_percent" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          stat    = "Average"
          period  = 300
          title   = "EC2 Memory Utilization"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 6
        height = 6
        properties = {
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWSPortfolioLab", "disk_used_percent", "path", "/", "InstanceId", aws_instance.web.id, "fstype", "xfs"]
          ]
          region = var.aws_region
          title  = "EC2 Disk Utilization"
          # Preserve the original omission of stat and period for this widget.
        }
      },
      {
        type   = "metric"
        x      = 18
        y      = 0
        width  = 6
        height = 6
        properties = {
          metrics = [
            ["AWS/EC2", "NetworkIn", "InstanceId", aws_instance.web.id],
            [".", "NetworkOut", ".", "."]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "EC2 Network Traffic"
          stat    = "Sum"
          period  = 300
        }
      }
    ]
  })
}
