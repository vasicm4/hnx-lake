data "aws_caller_identity" "current" {}


resource "aws_security_group" "superset" {
  name        = "visor-inc-superset-sg"
  description = "superset ui i postgres ludacki"
  vpc_id      = var.vpc_id
  tags        = { Name = "visor-inc-superset-sg" }
}

resource "aws_security_group" "loader" {
  name        = "visor-inc-loader-lambda-sg"
  description = "Loader Lambda egress to S3 (gw endpoint) and Postgres"
  vpc_id      = var.vpc_id
  tags        = { Name = "visor-inc-loader-lambda-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "superset_ui" {
  security_group_id = aws_security_group.superset.id
  cidr_ipv4         = var.superset_ingress_cidr
  from_port         = 8088
  to_port           = 8088
  ip_protocol       = "tcp"
  description       = "Superset UI"
}

resource "aws_vpc_security_group_ingress_rule" "superset_pg_from_loader" {
  security_group_id            = aws_security_group.superset.id
  referenced_security_group_id = aws_security_group.loader.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "Postgres from loader Lambda"
}

resource "aws_vpc_security_group_egress_rule" "superset_egress_all" {
  security_group_id = aws_security_group.superset.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Egress for docker image pulls, package repos, SSM"
}

resource "aws_vpc_security_group_egress_rule" "loader_https" {
  security_group_id = aws_security_group.loader.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "HTTPS for S3 gateway endpoint"
}

resource "aws_vpc_security_group_egress_rule" "loader_to_pg" {
  security_group_id            = aws_security_group.loader.id
  referenced_security_group_id = aws_security_group.superset.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "Postgres to EC2"
}


resource "aws_iam_role" "superset_ec2" {
  name = "visor-inc-superset-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "superset_ssm" {
  role       = aws_iam_role.superset_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "superset" {
  name = "visor-inc-superset-instance-profile"
  role = aws_iam_role.superset_ec2.name
}


data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_instance" "superset" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = var.public_subnet_id
  vpc_security_group_ids      = [aws_security_group.superset.id]
  iam_instance_profile        = aws_iam_instance_profile.superset.name
  associate_public_ip_address = true

  root_block_device {
    volume_size = 20 # Superset (-dev) + Postgres images need > default 8GB
    volume_type = "gp3"
  }

  user_data                   = templatefile("${path.module}/user_data.sh.tpl", {
    db_user                 = var.db_user
    db_password             = var.db_password
    superset_db_name        = var.superset_db_name
    metrics_db_name         = var.metrics_db_name
    superset_secret_key     = var.superset_secret_key
    superset_admin_user     = var.superset_admin_user
    superset_admin_password = var.superset_admin_password
    superset_image          = var.superset_image
  })
  user_data_replace_on_change = true

  tags = { Name = "visor-inc-superset" }
}


data "archive_file" "loader_zip" {
  type        = "zip"
  source_file = "${path.module}/loader_lambda.py"
  output_path = "${path.module}/loader_lambda.zip"
}

resource "aws_lambda_function" "loader" {
  filename         = data.archive_file.loader_zip.output_path
  source_code_hash = data.archive_file.loader_zip.output_base64sha256
  layers           = [var.awssdkpandas_layer_arn]

  function_name = "visor-inc-loader-lambda"
  role          = var.lambda_role_arn
  handler       = "loader_lambda.lambda_handler"
  runtime       = "python3.12"
  timeout       = 900
  memory_size   = 1024

  vpc_config {
    subnet_ids         = [var.private_subnet_id]
    security_group_ids = [aws_security_group.loader.id]
  }

  environment {
    variables = {
      GOLD_BUCKET_NAME    = var.gold_bucket_name
      DB_HOST             = aws_instance.superset.private_ip
      DB_PORT             = "5432"
      DB_NAME             = var.metrics_db_name
      DB_USER             = var.db_user
      DB_PASSWORD         = var.db_password
      DISCORD_WEBHOOK_URL = var.discord_webhook_url
    }
  }
}

resource "aws_cloudwatch_log_group" "loader_logs" {
  name              = "/aws/lambda/${aws_lambda_function.loader.function_name}"
  retention_in_days = 14
  tags              = { Name = "visor-inc-loader-lambda-logs" }
}

resource "aws_cloudwatch_event_rule" "loader_daily" {
  name                = "visor-inc-daily-loader"
  description         = "Load gold metrics into Postgres, after gold Lambda"
  schedule_expression = "cron(0 4 * * ? *)"
}

resource "aws_cloudwatch_event_target" "loader_target" {
  rule      = aws_cloudwatch_event_rule.loader_daily.name
  target_id = "loader-lambda"
  arn       = aws_lambda_function.loader.arn
}

resource "aws_lambda_permission" "loader_allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridgeLoader"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.loader.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.loader_daily.arn
}
