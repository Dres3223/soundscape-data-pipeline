output "bucket_name" {
  description = "Bucket for the pipeline's data"
  value       = aws_s3_bucket.data.bucket
}

output "pipeline_user_name" {
  description = "IAM user the pipeline runs as"
  value       = aws_iam_user.pipeline.name
}
