output "superset_public_ip" {
  value       = aws_instance.superset.public_ip
  description = "Public IP of the Superset/Postgres EC2 instance"
}

output "superset_url" {
  value       = "http://${aws_instance.superset.public_ip}:8088"
  description = "Superset UI URL"
}

output "superset_instance_id" {
  value       = aws_instance.superset.id
  description = "EC2 instance id"
}

output "superset_private_ip" {
  value       = aws_instance.superset.private_ip
  description = "Private IP the loader Lambda connects to on 5432"
}

output "loader_lambda_name" {
  value       = aws_lambda_function.loader.function_name
}
