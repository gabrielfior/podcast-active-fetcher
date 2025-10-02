provider "aws" {
  region = "us-east-1"  # Change this to your preferred AWS region
}

# Create a clean build directory and install dependencies
resource "null_resource" "prepare_lambda_package" {
  # Rebuild when any Python files change
  triggers = {
    requirements = filemd5("${path.module}/pyproject.toml")
    source_code = join(
      "",
      [for f in fileset(path.module, "**/*.py") : filemd5("${path.module}/${f}")]
    )
  }

  # Create the directory structure and install dependencies
  provisioner "local-exec" {
    command = <<EOT
      # Create clean build directory
      rm -rf ${path.module}/.lambda_build
      mkdir -p ${path.module}/.lambda_build
      
      # Copy source code
      cp -r ${path.module}/podcast_fetcher ${path.module}/.lambda_build/
      cp ${path.module}/pyproject.toml ${path.module}/.lambda_build/
      cp ${path.module}/aws_lambda_function/lambda_function.py ${path.module}/.lambda_build/
      
      # Install required dependencies to the build directory
      python -m pip install -r ${path.module}/requirements-lambda.txt --target ${path.module}/.lambda_build/
      
      # Clean up unnecessary files
      cd ${path.module}/.lambda_build
      find . -type d -name "__pycache__" -exec rm -rf {} + || true
      find . -name "*.pyc" -delete || true
      find . -name "*.dist-info" -exec rm -rf {} + || true
      find . -name "*.egg-info" -exec rm -rf {} + || true
      
      # Make sure all required files are included
      touch -t 202001010000.00 ./*
    EOT
  }
}

# Package the Lambda function code and its dependencies
data "archive_file" "lambda_zip" {
  depends_on  = [null_resource.prepare_lambda_package]
  type        = "zip"
  output_path = "${path.module}/lambda_function.zip"
  source_dir  = "${path.module}/.lambda_build"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info", "*.egg-info"]
}

# IAM role for the Lambda function
resource "aws_iam_role" "lambda_exec" {
  name = "podcast-fetcher-lambda-role"

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

# Attach the basic execution policy to the IAM role
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Custom policy for Lambda to access necessary AWS services
resource "aws_iam_policy" "lambda_policy" {
  name        = "podcast-fetcher-lambda-policy"
  description = "Policy for podcast fetcher Lambda function"
  
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
      # Add any additional permissions your Lambda might need here
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_custom" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

# The Lambda function
resource "aws_lambda_function" "podcast_fetcher" {
  function_name    = "podcast-fetcher"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.9"
  timeout          = 300  # 5 minutes
  memory_size      = 256
  
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  
  environment {
    variables = {
      # Add any environment variables your Lambda needs here
      PYTHONPATH = "/var/task"
    }
  }
}

# CloudWatch Event Rule to trigger the Lambda every hour
resource "aws_cloudwatch_event_rule" "hourly_schedule" {
  name                = "podcast-fetcher-hourly"
  description         = "Trigger podcast fetcher Lambda every hour"
  schedule_expression = "rate(1 hour)"
}

# Permission for CloudWatch to invoke the Lambda
resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.podcast_fetcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly_schedule.arn
}

# Connect the CloudWatch Event Rule to the Lambda
resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.hourly_schedule.name
  target_id = "lambda-target"
  arn       = aws_lambda_function.podcast_fetcher.arn
}

# Output the Lambda function name and ARN
output "lambda_function_name" {
  value = aws_lambda_function.podcast_fetcher.function_name
}

output "lambda_function_arn" {
  value = aws_lambda_function.podcast_fetcher.arn
}