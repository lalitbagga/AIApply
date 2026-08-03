variable "prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "github_repo" {
  type        = string
  description = "GitHub repo in 'owner/repo-name' format, e.g. 'johnsmith/AIApply'"
}

# --- Register GitHub as OIDC identity provider (one per AWS account) ---
# This lets GitHub Actions prove its identity to AWS without storing any long-lived keys.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# --- IAM role that GitHub Actions assumes ---
resource "aws_iam_role" "github_actions" {
  name = "${var.prefix}-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Only allow this specific repo (not any random GitHub repo)
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*"
        }
      }
    }]
  })
}

# --- Permissions: exactly what CI/CD needs, nothing more ---
resource "aws_iam_role_policy" "github_deploy" {
  name = "${var.prefix}-github-deploy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "FrontendDeploy"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = "*"
      },
      {
        Sid      = "CloudFrontInvalidate"
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation"]
        Resource = "*"
      },
      {
        Sid    = "LambdaDeploy"
        Effect = "Allow"
        Action = [
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:GetFunction"
        ]
        Resource = "*"
      },
      {
        Sid    = "TerraformState"
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket",
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"
        ]
        Resource = [
          "arn:aws:s3:::aiapply-terraform-state-924029800762",
          "arn:aws:s3:::aiapply-terraform-state-924029800762/*",
          "arn:aws:dynamodb:*:*:table/terraform-locks"
        ]
      },
      {
        Sid    = "TerraformApply"
        Effect = "Allow"
        Action = [
          "iam:*",
          "lambda:*",
          "apigateway:*",
          "s3:*",
          "cloudfront:*",
          "cognito-idp:*",
          "sqs:*",
          "dynamodb:*",
          "logs:*",
          "ssm:*",
          "secretsmanager:*"
        ]
        Resource = "*"
      }
    ]
  })
}

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions.arn
  description = "Paste this into GitHub → Settings → Environments → production → Variables → AWS_DEPLOY_ROLE_ARN"
}
