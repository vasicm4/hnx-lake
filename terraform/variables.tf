variable "discord_webhook_url" {
  type        = string
  description = "Discord webhook URL for Lambda notifications"
  sensitive   = true
}