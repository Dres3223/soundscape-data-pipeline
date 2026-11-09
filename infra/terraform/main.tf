# Object storage for the pipeline: raw audio and Parquet features
resource "aws_s3_bucket" "data" {
  bucket        = var.bucket_name
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3: no extra cost, unlike KMS keys
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Identity of the pipeline. Its access key is created and deleted outside
# Terraform (scripts/create_pipeline_key.py), so the secret never reaches the
# state; `make infra-destroy` deletes the key first, as AWS requires.
resource "aws_iam_user" "pipeline" {
  name = var.pipeline_user_name
}

# Least privilege: list, read and write this bucket only. No s3:DeleteObject:
# the pipeline never deletes, so a leaked key cannot delete the raw data.
data "aws_iam_policy_document" "pipeline" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
}

resource "aws_iam_user_policy" "pipeline" {
  name   = "pipeline-bucket-access"
  user   = aws_iam_user.pipeline.name
  policy = data.aws_iam_policy_document.pipeline.json
}
