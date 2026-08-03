variable "prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "lambda_function_names" {
  type = map(string)
}

# --- CloudWatch Log Groups for each Lambda ---
# Free at personal scale (5 GB ingestion + 5 GB storage free per month).
# Alarms ($0.10/alarm/mo) and dashboard ($3/mo) removed to keep cost at $0.
# To debug: AWS Console → CloudWatch → Log Groups → /aws/lambda/<name>
resource "aws_cloudwatch_log_group" "lambda_logs" {
  for_each          = var.lambda_function_names
  name              = "/aws/lambda/${each.value}"
  retention_in_days = 14
}
