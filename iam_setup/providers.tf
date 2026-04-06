terraform {
  backend "s3" {
    bucket         = "visor-inc-terraform-state"
    key            = "global/iam/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-state-lock"
    encrypt        = true
    profile        = "cloud-projekat-dev" 
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = "us-east-1"
  profile = "cloud-projekat-dev"
}

data "aws_caller_identity" "current" {}