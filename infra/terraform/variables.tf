variable "aws_endpoint_url" {
  description = "AWS API endpoint of an emulator; null means real AWS"
  type        = string
  default     = null
}

variable "aws_region" {
  description = "AWS region of the bucket"
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "Bucket for the pipeline's data; globally unique on real AWS"
  type        = string
}

variable "pipeline_user_name" {
  description = "IAM user the pipeline runs as"
  type        = string
  default     = "soundscape-pipeline"
}

variable "force_destroy" {
  description = "Let terraform destroy delete the bucket even if it holds data"
  type        = bool
  default     = false
}
