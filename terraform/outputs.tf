output "iam_user_credentials" {
  value     = module.iam.user_credentials
  sensitive = true
}

output "iam_account_id" {
  value = module.iam.account_id
}