variable "prefix" {
  type = string
}

variable "environment" {
  type = string
}

# --- S3 Bucket for CV uploads and generated documents ---
resource "aws_s3_bucket" "cv_storage" {
  bucket = "${var.prefix}-cv-storage-924029800762"
}

resource "aws_s3_bucket_versioning" "cv_storage" {
  bucket = aws_s3_bucket.cv_storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Expire old object versions after 30 days so deleted/replaced CVs don't accumulate storage costs
resource "aws_s3_bucket_lifecycle_configuration" "cv_storage" {
  bucket = aws_s3_bucket.cv_storage.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cv_storage" {
  bucket = aws_s3_bucket.cv_storage.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cv_storage" {
  bucket                  = aws_s3_bucket.cv_storage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_cors_configuration" "cv_storage" {
  bucket = aws_s3_bucket.cv_storage.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "POST", "GET"]
    allowed_origins = ["*"] # Tighten in production
    max_age_seconds = 3000
  }
}

# --- DynamoDB Tables ---

resource "aws_dynamodb_table" "users" {
  name         = "${var.prefix}-users"
  billing_mode = "PAY_PER_REQUEST" # No free tier for on-demand, but <$0.01/mo at personal scale
  hash_key     = "userId"

  attribute {
    name = "userId"
    type = "S"
  }
}

resource "aws_dynamodb_table" "cvs" {
  name         = "${var.prefix}-cvs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "userId"
  range_key    = "cvId"

  attribute {
    name = "userId"
    type = "S"
  }

  attribute {
    name = "cvId"
    type = "S"
  }
}

resource "aws_dynamodb_table" "job_listings" {
  name         = "${var.prefix}-job-listings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "jobId"

  attribute {
    name = "jobId"
    type = "S"
  }

  attribute {
    name = "source"
    type = "S"
  }

  attribute {
    name = "postedAt"
    type = "S"
  }

  global_secondary_index {
    name            = "source-postedAt-index"
    hash_key        = "source"
    range_key       = "postedAt"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "applications" {
  name         = "${var.prefix}-applications"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "userId"
  range_key    = "applicationId"

  attribute {
    name = "userId"
    type = "S"
  }

  attribute {
    name = "applicationId"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  global_secondary_index {
    name            = "userId-status-index"
    hash_key        = "userId"
    range_key       = "status"
    projection_type = "ALL"
  }
}

# --- Outputs ---
output "cv_bucket_name" {
  value = aws_s3_bucket.cv_storage.id
}

output "cv_bucket_arn" {
  value = aws_s3_bucket.cv_storage.arn
}

output "dynamodb_table_arns" {
  value = [
    aws_dynamodb_table.users.arn,
    aws_dynamodb_table.cvs.arn,
    aws_dynamodb_table.job_listings.arn,
    aws_dynamodb_table.applications.arn,
  ]
}
