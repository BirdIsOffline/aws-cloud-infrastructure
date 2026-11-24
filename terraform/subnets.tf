locals {
  # Stable keys keep subnet and association addresses consistent during adoption.
  public_subnets = {
    public_1 = {
      name              = "aws-lab-public-1"
      cidr_block        = "10.20.1.0/24"
      availability_zone = "us-east-2a"
    }
    public_2 = {
      name              = "aws-lab-public-2"
      cidr_block        = "10.20.2.0/24"
      availability_zone = "us-east-2b"
    }
  }

  private_subnets = {
    private_1 = {
      name              = "aws-lab-private-1"
      cidr_block        = "10.20.11.0/24"
      availability_zone = "us-east-2a"
    }
    private_2 = {
      name              = "aws-lab-private-2"
      cidr_block        = "10.20.12.0/24"
      availability_zone = "us-east-2b"
    }
  }
}

resource "aws_subnet" "public" {
  for_each = local.public_subnets

  vpc_id            = aws_vpc.lab.id
  cidr_block        = each.value.cidr_block
  availability_zone = each.value.availability_zone

  # Public routing does not require subnet-level public IP auto-assignment.
  map_public_ip_on_launch                        = false
  assign_ipv6_address_on_creation                = false
  ipv6_native                                    = false
  enable_dns64                                   = false
  private_dns_hostname_type_on_launch            = "ip-name"
  enable_resource_name_dns_a_record_on_launch    = false
  enable_resource_name_dns_aaaa_record_on_launch = false

  tags = {
    Name = each.value.name
  }
}

resource "aws_subnet" "private" {
  for_each = local.private_subnets

  vpc_id            = aws_vpc.lab.id
  cidr_block        = each.value.cidr_block
  availability_zone = each.value.availability_zone

  map_public_ip_on_launch                        = false
  assign_ipv6_address_on_creation                = false
  ipv6_native                                    = false
  enable_dns64                                   = false
  private_dns_hostname_type_on_launch            = "ip-name"
  enable_resource_name_dns_a_record_on_launch    = false
  enable_resource_name_dns_aaaa_record_on_launch = false

  tags = {
    Name = each.value.name
  }
}
