resource "aws_iam_role" "lambda_exec" {
  name = "visor-inc-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_s3_write" {
  name = "lambda-s3-write-policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = ["${var.bronze_bucket_arn}/*"]
    }]
  })
}

resource "aws_security_group" "lambda_sg" {
  name        = "visor-inc-lambda-sg"
  description = "Security group for Lambda in private subnet"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS for API calls"
  }

  egress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP for HN Search API"
  }
}

data "archive_file" "bronze_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/bronze/bronze_lambda.py"
  output_path = "${path.module}/bronze_lambda.zip"
}

resource "null_resource" "build_silver_lambda" {
  provisioner "local-exec" {
    command = <<-EOT
      rm -rf ${path.module}/build/silver
      mkdir -p ${path.module}/build/silver

      docker run --rm \
        -v ${abspath(path.module)}/silver:/workspace/silver \
        -v ${abspath(path.module)}/build:/workspace/build \
        python:3.12-slim \
        /bin/bash -c "
          pip install -r /workspace/silver/requirements.txt \
            -t /workspace/build/silver &&
          cp /workspace/silver/silver_lambda.py \
            /workspace/build/silver/
        "
    EOT
  }
}

data "archive_file" "silver_lambda_zip" {
  depends_on = [null_resource.build_silver_lambda]
  type        = "zip"
  source_dir = "${path.module}/build/silver"
  output_path = "${path.module}/silver_lambda.zip"
}

resource "aws_lambda_function" "hackernews_fetch" {
  filename         = data.archive_file.bronze_lambda_zip.output_path
  source_code_hash = data.archive_file.bronze_lambda_zip.output_base64sha256

  function_name = "visor-inc-test-fetch"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "bronze_lambda.lambda_handler"
  runtime       = "python3.12"
  timeout       = 900
  memory_size   = 512

  vpc_config {
    subnet_ids         = [var.private_subnet_id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  environment {
    variables = {
      BRONZE_BUCKET_NAME   = var.bronze_bucket_name
      DISCORD_WEBHOOK_URL  = var.discord_webhook_url
    }
  }
}

resource "aws_lambda_function" "silver_lambda" {
  filename         = data.archive_file.silver_lambda_zip.output_path
  source_code_hash = data.archive_file.silver_lambda_zip.output_base64sha256

  function_name = "visor-inc-silver-lambda"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "silver_lambda.lambda_handler"
  runtime       = "python3.12"
  timeout       = 900
  memory_size   = 512

  vpc_config {
    subnet_ids         = [var.private_subnet_id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  environment {
    variables = {
      BRONZE_BUCKET_NAME   = var.bronze_bucket_name
      SILVER_BUCKET_NAME   = var.silver_bucket_name
      DISCORD_WEBHOOK_URL  = var.discord_webhook_url
    }
  }
}

resource "aws_cloudwatch_event_rule" "daily_trigger" {
  name                = "visor-inc-daily-data-collection"
  description         = "Trigger data collection daily"
  schedule_expression = "cron(0 1 * * ? *)"
}

resource "aws_cloudwatch_event_rule" "silver_daily_trigger" {
  name                = "visor-inc-daily-silver-processing"
  description         = "Trigger silver lambda daily"
  schedule_expression = "cron(0 2 * * ? *)"
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.daily_trigger.name
  target_id = "hackernews-fetch-lambda"
  arn       = aws_lambda_function.hackernews_fetch.arn
}

resource "aws_cloudwatch_event_target" "silver_lambda_target" {
  rule      = aws_cloudwatch_event_rule.silver_daily_trigger.name
  target_id = "silver-lambda"
  arn       = aws_lambda_function.silver_lambda.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.hackernews_fetch.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_trigger.arn
}

resource "aws_lambda_permission" "silver_allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridgeSilver"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.silver_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.silver_daily_trigger.arn
}

# resource "aws_cloudwatch_log_group" "lambda_logs" {
#   name              = "/aws/lambda/${aws_lambda_function.hackernews_fetch.function_name}"
#   retention_in_days = 14
#
#   tags = {
#     Name = "visor-inc-lambda-logs"
#   }
# }