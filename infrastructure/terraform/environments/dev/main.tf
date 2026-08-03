locals {
  prefix = "${var.project_name}-${var.environment}"
}

# --- Storage (S3 + DynamoDB) ---
module "storage" {
  source      = "../../modules/storage"
  prefix      = local.prefix
  environment = var.environment
}

# --- CDN (S3 + CloudFront for frontend) ---
module "cdn" {
  source              = "../../modules/cdn"
  prefix              = local.prefix
  environment         = var.environment
  domain_name         = var.custom_domain
  acm_certificate_arn = var.acm_certificate_arn
}

# --- Auth (Cognito) ---
module "auth" {
  source      = "../../modules/auth"
  prefix      = local.prefix
  environment = var.environment
}

# --- Queue (SQS) ---
module "queue" {
  source      = "../../modules/queue"
  prefix      = local.prefix
  environment = var.environment
}

# --- API (API Gateway + Lambda) ---
module "api" {
  source                  = "../../modules/api"
  prefix                  = local.prefix
  environment             = var.environment
  anthropic_api_key       = var.anthropic_api_key
  stripe_secret_key       = var.stripe_secret_key
  stripe_webhook_secret   = var.stripe_webhook_secret
  frontend_url            = var.frontend_url
  cv_bucket_name          = module.storage.cv_bucket_name
  cv_bucket_arn           = module.storage.cv_bucket_arn
  dynamodb_table_arns     = module.storage.dynamodb_table_arns
  sqs_queue_arns          = [module.queue.job_scout_queue_arn, module.queue.cv_tailor_queue_arn]
  sqs_job_scout_queue_url = module.queue.job_scout_queue_url
  sqs_cv_tailor_queue_url = module.queue.cv_tailor_queue_url
  sqs_job_scout_queue_arn = module.queue.job_scout_queue_arn
  sqs_cv_tailor_queue_arn = module.queue.cv_tailor_queue_arn
  cognito_user_pool_arn   = module.auth.user_pool_arn
}

# --- Monitoring (CloudWatch) ---
module "monitoring" {
  source                = "../../modules/monitoring"
  prefix                = local.prefix
  environment           = var.environment
  lambda_function_names = module.api.lambda_function_names
}

# --- CI/CD (GitHub OIDC role for GitHub Actions) ---
module "cicd" {
  source      = "../../modules/cicd"
  prefix      = local.prefix
  environment = var.environment
  github_repo = var.github_repo
}
