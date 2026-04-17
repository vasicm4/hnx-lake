resource "aws_iam_user" "users" {
  for_each = local.all_users
  name     = each.key
}

resource "aws_iam_group" "developers" {
  name = "developers"
}

resource "aws_iam_group_membership" "team" {
  name  = "dev-membership"
  users = local.developers
  group = aws_iam_group.developers.name
}

resource "aws_iam_group_policy_attachment" "dev_attach" {
  for_each   = toset(local.dev_policies)
  group      = aws_iam_group.developers.name
  policy_arn = each.value
}

resource "aws_iam_user_policy_attachment" "admin_access" {
  user       = aws_iam_user.users["iamadmin"].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_user_login_profile" "login" {
  for_each        = aws_iam_user.users
  user            = each.value.name
  password_length = 16
}

resource "aws_iam_access_key" "keys" {
  for_each = aws_iam_user.users
  user     = each.value.name
}