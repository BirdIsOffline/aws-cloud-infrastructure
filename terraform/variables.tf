variable "aws_region" {
  description = "AWS Region containing the existing portfolio infrastructure."
  type        = string
  default     = "us-east-2"
}

variable "web_ami_name" {
  description = "Exact Amazon-owned AL2023 x86_64 AMI name approved for adoption. Changing it can replace the instance."
  type        = string
  default     = "al2023-ami-2023.12.20261120.0-kernel-6.18-x86_64"

  validation {
    condition = (
      startswith(var.web_ami_name, "al2023-ami-") &&
      endswith(var.web_ami_name, "-x86_64") &&
      !strcontains(var.web_ami_name, "*") &&
      !strcontains(var.web_ami_name, "?")
    )
    error_message = "Use an exact Amazon Linux 2023 x86_64 AMI name without wildcard characters."
  }
}
