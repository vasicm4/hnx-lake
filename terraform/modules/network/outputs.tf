output "s3_vpce_id" {
  value = aws_vpc_endpoint.s3.id
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_id" {
  value = aws_subnet.private.id
}