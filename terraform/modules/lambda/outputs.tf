output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.hackernews_fetch.arn
}

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.hackernews_fetch.function_name
}

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_exec.arn
}

output "cloudwatch_event_rule_arn" {
  description = "ARN of the CloudWatch Event Rule"
  value       = aws_cloudwatch_event_rule.daily_trigger.arn
}