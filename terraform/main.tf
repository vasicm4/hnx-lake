module "iam" {
  source = "./modules/iam"
}

module "network" {
  source = "./modules/network"
}

module "bronze_bucket" {
  source          = "./modules/s3"
  bucket_name     = "visor-inc-amazing-datalake-bronze"
  layer_name      = "Bronze"
  vpc_endpoint_id = module.network.s3_vpce_id
}

module "silver_bucket" {
  source          = "./modules/s3"
  bucket_name     = "visor-inc-amazing-datalake-silver"
  layer_name      = "Silver"
  vpc_endpoint_id = module.network.s3_vpce_id
}

module "gold_bucket" {
  source          = "./modules/s3"
  bucket_name     = "visor-inc-amazing-datalake-gold"
  layer_name      = "Gold"
  vpc_endpoint_id = module.network.s3_vpce_id
}

module "lambda" {
  source              = "./modules/lambda"
  vpc_id              = module.network.vpc_id
  private_subnet_id   = module.network.private_subnet_id
  bronze_bucket_arn   = module.bronze_bucket.bucket_arn
  bronze_bucket_name  = "visor-inc-amazing-datalake-bronze"
  silver_bucket_name  = "visor-inc-amazing-datalake-silver"
  discord_webhook_url = var.discord_webhook_url
  silver_bucket_arn   = module.silver_bucket.bucket_arn
  gold_bucket_name    = "visor-inc-amazing-datalake-gold"
  gold_bucket_arn     = module.gold_bucket.bucket_arn
}

module "visualization" {
  source            = "./modules/visualization"
  vpc_id            = module.network.vpc_id
  public_subnet_id  = module.network.public_subnet_id
  private_subnet_id = module.network.private_subnet_id
  lambda_role_arn   = module.lambda.lambda_role_arn
  gold_bucket_name  = "visor-inc-amazing-datalake-gold"
  gold_bucket_arn   = module.gold_bucket.bucket_arn
  discord_webhook_url = var.discord_webhook_url
  db_password             = var.db_password
  superset_admin_password = var.superset_admin_password
  superset_secret_key     = var.superset_secret_key
  superset_ingress_cidr   = var.superset_ingress_cidr
}