locals {
  dev_policies = [
    "arn:aws:iam::aws:policy/AmazonS3FullAccess",
    "arn:aws:iam::aws:policy/AWSLambda_FullAccess",
    "arn:aws:iam::aws:policy/AmazonEC2FullAccess",
    "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
    "arn:aws:iam::aws:policy/IAMFullAccess"
  ]

  all_users = {
    "iamadmin" = "admin"
    "iammaksim" = "developer"
    "iamnikola" = "developer"
    "iamdjordje" = "developer"
  }
  
  developers = [for name, role in local.all_users : name if role == "developer"]
}