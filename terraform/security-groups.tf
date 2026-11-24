# Preserve the existing untagged group. Rules are managed separately below.
# Do not add inline ingress or egress definitions to this resource.
resource "aws_security_group" "web" {
  name        = "aws-lab-web-sg"
  description = "Security group for AWS lab web server"
  vpc_id      = aws_vpc.lab.id
}

resource "aws_vpc_security_group_ingress_rule" "web_http" {
  security_group_id = aws_security_group.web.id
  description       = "Allow public HTTP for lab web server"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "web_all_ipv4" {
  security_group_id = aws_security_group.web.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"

  # All protocols includes all ports; preserve the absence of a description.
}
