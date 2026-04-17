module "iam" {
  source = "./modules/iam"
}

module "bronze_bucket" {
  source      = "./modules/s3"
  bucket_name = "visor-inc-amazing-datalake-bronze"
  layer_name  = "Bronze"
}

module "silver_bucket" {
  source      = "./modules/s3"
  bucket_name = "visor-inc-amazing-datalake-silver"
  layer_name  = "Silver"
}

module "gold_bucket" {
  source      = "./modules/s3"
  bucket_name = "visor-inc-amazing-datalake-gold"
  layer_name  = "Gold"
}