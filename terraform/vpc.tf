resource "aws_vpc" "lab" {
  cidr_block                       = "10.20.0.0/16"
  instance_tenancy                 = "default"
  enable_dns_support               = true
  enable_dns_hostnames             = false
  assign_generated_ipv6_cidr_block = false

  tags = {
    Name = "aws-cloud-lab-vpc"
  }

  # Retain during adoption to block planned VPC destruction or replacement.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id

  tags = {
    Name = "aws-lab-igw"
  }
}
