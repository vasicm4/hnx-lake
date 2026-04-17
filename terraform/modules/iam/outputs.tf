output "account_id" { 
  value = data.aws_caller_identity.current.account_id 
}

output "user_credentials" {
  sensitive = true
  value = {
    for u in aws_iam_user.users : u.name => {
      access_key = aws_iam_access_key.keys[u.name].id
      secret_key = aws_iam_access_key.keys[u.name].secret
      password   = aws_iam_user_login_profile.login[u.name].password
    }
  }
}