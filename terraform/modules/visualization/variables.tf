variable "vpc_id" {
  type = string
}

variable "public_subnet_id" {
  type        = string
  description = "Public subnet for the Superset + Postgres EC2 instance"
}

variable "private_subnet_id" {
  type        = string
  description = "Private subnet for the loader Lambda (same as the other lambdas)"
}

variable "lambda_role_arn" {
  type        = string
  description = "Reuse the existing visor-inc-lambda-role (already has gold S3 read + VPC access)"
}

variable "gold_bucket_name" {
  type = string
}

variable "gold_bucket_arn" {
  type = string
}

variable "discord_webhook_url" {
  type      = string
  sensitive = true
}

variable "awssdkpandas_layer_arn" {
  type        = string
  default     = "arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python312:3"
  description = "Same managed layer the gold Lambda uses (bundles pg8000)"
}

# ---- EC2 / Superset ----
variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "superset_image" {
  type        = string
  default     = "apache/superset:latest-dev"
  description = "MUST be a -dev tag: lean Superset images ship no Postgres driver. Pin to e.g. apache/superset:6.1.0-dev for reproducibility (verify the tag exists on Docker Hub first)."
}

variable "superset_ingress_cidr" {
  type        = string
  default     = "0.0.0.0/0"
  description = "CIDR allowed to reach the Superset UI on port 8088. Restrict to your IP for least-privilege points; leave open only if your defense IP is unpredictable (or use SSM port-forwarding instead)."
}

# ---- Database / Superset credentials ----
variable "db_user" {
  type    = string
  default = "hnx"
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "metrics_db_name" {
  type    = string
  default = "metrics"
}

variable "superset_db_name" {
  type    = string
  default = "superset"
}

variable "superset_admin_user" {
  type    = string
  default = "admin"
}

variable "superset_admin_password" {
  type      = string
  sensitive = true
}

variable "superset_secret_key" {
  type        = string
  sensitive   = true
  description = "Superset SECRET_KEY. Generate with: openssl rand -base64 42"
}
