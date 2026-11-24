# Leave the VPC's unnamed main route table and automatic local routes unmanaged.
# Routes are separate resources; do not add inline route definitions here.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id

  tags = {
    Name = "aws-lab-public-rt"
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.lab.id

  tags = {
    Name = "aws-lab-private-rt"
  }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.lab.id
}

resource "aws_route_table_association" "public" {
  for_each = local.public_subnets

  subnet_id      = aws_subnet.public[each.key].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  for_each = local.private_subnets

  subnet_id      = aws_subnet.private[each.key].id
  route_table_id = aws_route_table.private.id
}
