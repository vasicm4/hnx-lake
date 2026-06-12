module "iam" {
  source = "./modules/iam"
}

module "network" {
  source = "./modules/network"
}

module "bronze_bucket" {
  source      = "./modules/s3"
  bucket_name = "visor-inc-amazing-datalake-bronze"
  layer_name  = "Bronze"
  vpc_endpoint_id = module.network.s3_vpce_id
}

module "silver_bucket" {
  source      = "./modules/s3"
  bucket_name = "visor-inc-amazing-datalake-silver"
  layer_name  = "Silver"
  vpc_endpoint_id = module.network.s3_vpce_id
}

module "gold_bucket" {
  source      = "./modules/s3"
  bucket_name = "visor-inc-amazing-datalake-gold"
  layer_name  = "Gold"
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
}