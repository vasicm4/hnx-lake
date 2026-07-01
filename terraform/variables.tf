variable "discord_webhook_url" {
  type        = string
  description = "Discord webhook URL for Lambda notifications"
  sensitive   = true
}

variable "db_password" { 
  type = string
  sensitive = true 
}

variable "superset_admin_password" { 
  type = string
  sensitive = true 
}

variable "superset_secret_key" { 
  type = string
  sensitive = true 
}

variable "superset_ingress_cidr" { 
  type = string
  default = "0.0.0.0/0"
}