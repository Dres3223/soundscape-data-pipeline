locals {
  emulated = var.aws_endpoint_url != null
}

provider "aws" {
  region = var.aws_region

  # An emulator has no real account to look up, and no per-bucket hostnames
  s3_use_path_style           = local.emulated
  skip_credentials_validation = local.emulated
  skip_metadata_api_check     = local.emulated
  skip_requesting_account_id  = local.emulated

  dynamic "endpoints" {
    for_each = local.emulated ? [var.aws_endpoint_url] : []
    content {
      s3  = endpoints.value
      iam = endpoints.value
      sts = endpoints.value
    }
  }
}
