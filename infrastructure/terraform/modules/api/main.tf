variable "prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
}

variable "cv_bucket_name" {
  type = string
}

variable "cv_bucket_arn" {
  type = string
}

variable "dynamodb_table_arns" {
  type = list(string)
}

variable "sqs_queue_arns" {
  type = list(string)
}

variable "sqs_job_scout_queue_arn" {
  type = string
}

variable "sqs_cv_tailor_queue_arn" {
  type = string
}

variable "cognito_user_pool_arn" {
  type = string
}

variable "stripe_secret_key" {
  type      = string
  sensitive = true
}

variable "stripe_webhook_secret" {
  type      = string
  sensitive = true
}

variable "frontend_url" {
  type        = string
  description = "CloudFront URL for Stripe redirect (e.g. https://dxxxxxxxxx.cloudfront.net)"
}

variable "sqs_job_scout_queue_url" {
  type = string
}

variable "sqs_cv_tailor_queue_url" {
  type = string
}

# --- Store API key in SSM Parameter Store (free, unlike Secrets Manager $0.40/mo) ---
resource "aws_ssm_parameter" "anthropic_key" {
  name  = "/${var.prefix}/anthropic-api-key"
  type  = "SecureString" # Encrypted with default aws/ssm KMS key (free)
  value = var.anthropic_api_key
}

resource "aws_ssm_parameter" "stripe_secret_key" {
  name  = "/${var.prefix}/stripe-secret-key"
  type  = "SecureString"
  value = var.stripe_secret_key
}

resource "aws_ssm_parameter" "stripe_webhook_secret" {
  name  = "/${var.prefix}/stripe-webhook-secret"
  type  = "SecureString"
  value = var.stripe_webhook_secret
}

# --- IAM Role for Lambda ---
resource "aws_iam_role" "lambda_role" {
  name = "${var.prefix}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.prefix}-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = "${var.cv_bucket_arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:BatchGetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = concat(var.dynamodb_table_arns, [for arn in var.dynamodb_table_arns : "${arn}/index/*"])
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = var.sqs_queue_arns
      },
      {
        Effect = "Allow"
        Action = ["ssm:GetParameter"]
        Resource = [
          aws_ssm_parameter.anthropic_key.arn,
          aws_ssm_parameter.stripe_secret_key.arn,
          aws_ssm_parameter.stripe_webhook_secret.arn,
        ]
      }
    ]
  })
}

# --- Lambda Functions ---

# CV Analyst: triggered by S3 upload
resource "aws_lambda_function" "cv_analyst" {
  function_name = "${var.prefix}-cv-analyst"
  role          = aws_iam_role.lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 300 # 5 minutes for CV parsing
  memory_size   = 512

  filename         = "${path.module}/placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/placeholder.zip")

  environment {
    variables = {
      ENVIRONMENT          = var.environment
      ANTHROPIC_PARAM_NAME = aws_ssm_parameter.anthropic_key.name
      CV_BUCKET            = var.cv_bucket_name
      SQS_JOB_SCOUT_URL    = var.sqs_job_scout_queue_url
    }
  }
}

# API Handler: serves REST API requests
resource "aws_lambda_function" "api_handler" {
  function_name = "${var.prefix}-api-handler"
  role          = aws_iam_role.lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 256

  filename         = "${path.module}/placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/placeholder.zip")

  environment {
    variables = {
      ENVIRONMENT               = var.environment
      ANTHROPIC_PARAM_NAME      = aws_ssm_parameter.anthropic_key.name
      STRIPE_SECRET_PARAM_NAME  = aws_ssm_parameter.stripe_secret_key.name
      STRIPE_WEBHOOK_PARAM_NAME = aws_ssm_parameter.stripe_webhook_secret.name
      FRONTEND_URL              = var.frontend_url
      CV_BUCKET                 = var.cv_bucket_name
      SQS_JOB_SCOUT_URL         = var.sqs_job_scout_queue_url
    }
  }
}

# Job Scout: triggered by SQS
resource "aws_lambda_function" "job_scout" {
  function_name = "${var.prefix}-job-scout"
  role          = aws_iam_role.lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 900 # 15 min max for job scraping
  memory_size   = 1024

  filename         = "${path.module}/placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/placeholder.zip")

  environment {
    variables = {
      ENVIRONMENT          = var.environment
      ANTHROPIC_PARAM_NAME = aws_ssm_parameter.anthropic_key.name
      CV_BUCKET            = var.cv_bucket_name
      CV_TAILOR_QUEUE_URL  = var.sqs_cv_tailor_queue_url
    }
  }
}

# CV Tailor: triggered by SQS
resource "aws_lambda_function" "cv_tailor" {
  function_name = "${var.prefix}-cv-tailor"
  role          = aws_iam_role.lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 300
  memory_size   = 512

  filename         = "${path.module}/placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/placeholder.zip")

  environment {
    variables = {
      ENVIRONMENT          = var.environment
      ANTHROPIC_PARAM_NAME = aws_ssm_parameter.anthropic_key.name
      CV_BUCKET            = var.cv_bucket_name
    }
  }
}

# --- S3 Event Trigger for CV Analyst ---
resource "aws_lambda_permission" "s3_trigger" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cv_analyst.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.cv_bucket_arn
}

resource "aws_s3_bucket_notification" "cv_upload" {
  bucket = var.cv_bucket_name

  lambda_function {
    lambda_function_arn = aws_lambda_function.cv_analyst.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
    filter_suffix       = ".pdf"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.cv_analyst.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
    filter_suffix       = ".docx"
  }

  depends_on = [aws_lambda_permission.s3_trigger]
}

# --- API Gateway HTTP API ---
resource "aws_apigatewayv2_api" "main" {
  name          = "${var.prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"] # Tighten in production
    allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers = ["*"]
    max_age       = 86400
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${var.prefix}-api"
  retention_in_days = 14
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_handler.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# --- SQS → Lambda event source mappings ---
# batch_size=1: each job scout / CV tailor runs in its own Lambda invocation
resource "aws_lambda_event_source_mapping" "job_scout_sqs" {
  event_source_arn = var.sqs_job_scout_queue_arn
  function_name    = aws_lambda_function.job_scout.arn
  batch_size       = 1
  enabled          = true
}

resource "aws_lambda_event_source_mapping" "cv_tailor_sqs" {
  event_source_arn = var.sqs_cv_tailor_queue_arn
  function_name    = aws_lambda_function.cv_tailor.arn
  batch_size       = 1
  enabled          = true
}

# --- Outputs ---
output "api_gateway_url" {
  value = aws_apigatewayv2_stage.default.invoke_url
}

output "lambda_function_names" {
  value = {
    cv_analyst  = aws_lambda_function.cv_analyst.function_name
    api_handler = aws_lambda_function.api_handler.function_name
    job_scout   = aws_lambda_function.job_scout.function_name
    cv_tailor   = aws_lambda_function.cv_tailor.function_name
  }
}
