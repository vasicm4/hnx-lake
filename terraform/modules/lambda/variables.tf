variable "vpc_id" {
  type        = string
}

variable "private_subnet_id" {
  type        = string
}

variable "bronze_bucket_arn" {
  type        = string
}

variable "bronze_bucket_name" {
  type        = string
  description = "Name of the bronze S3 bucket"
}

variable "discord_webhook_url" {
  type        = string
  description = "Discord webhook URL for notifications"
  sensitive   = true
}

variable "silver_bucket_name" {
  type        = string
  description = "Name of the silver S3 bucket"
}