terraform {
  backend "s3" {
    bucket         = "visor-inc-terraform-state"
    key            = "data-lake-project/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-state-lock"
    encrypt        = true
    profile        = "cloud-projekat-dev"
  }
}