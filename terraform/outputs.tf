output "iam_user_credentials" {
  value     = module.iam.user_credentials
  sensitive = true
}

output "iam_account_id" {
  value = module.iam.account_id
}

output "superset_url" {
  value = module.visualization.superset_url
}

output "superset_instance_id" {
  value = module.visualization.superset_instance_id
}

output "superset_public_ip" {
  value = module.visualization.superset_public_ip
}

output "loader_lambda_name" {
  value = module.visualization.loader_lambda_name
}