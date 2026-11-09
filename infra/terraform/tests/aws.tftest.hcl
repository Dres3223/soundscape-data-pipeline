# Checks the configuration for real AWS without an account: the provider is
# mocked, so no credentials or network are needed. It proves what the code
# asks AWS for, not that AWS accepts it (that needs P1PDPS-33).
# Run with: make infra-test (variables from envs/aws.tfvars.example)

mock_provider "aws" {
  # The mock invents values; this one must at least be a valid policy
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

run "real_aws_uses_no_emulator_and_protects_the_data" {
  command = apply

  assert {
    condition     = local.emulated == false
    error_message = "With the AWS settings no emulator endpoint may be used"
  }

  assert {
    condition     = aws_s3_bucket.data.force_destroy == false
    error_message = "On real AWS, destroy must refuse a bucket that holds data"
  }
}

run "bucket_is_encrypted_and_private" {
  command = apply

  assert {
    condition = (
      one(aws_s3_bucket_server_side_encryption_configuration.data.rule)
      .apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    )
    error_message = "The bucket must be encrypted with SSE-S3"
  }

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.data.block_public_acls,
      aws_s3_bucket_public_access_block.data.block_public_policy,
      aws_s3_bucket_public_access_block.data.ignore_public_acls,
      aws_s3_bucket_public_access_block.data.restrict_public_buckets,
    ])
    error_message = "All four public access blocks must be on"
  }
}

run "pipeline_policy_is_least_privilege" {
  command = apply

  assert {
    condition = (
      data.aws_iam_policy_document.pipeline.statement[0].actions == toset(["s3:ListBucket"]) &&
      data.aws_iam_policy_document.pipeline.statement[1].actions == toset(["s3:GetObject", "s3:PutObject"])
    )
    error_message = "The pipeline may only list, read and write"
  }

  assert {
    condition = (
      data.aws_iam_policy_document.pipeline.statement[0].resources == toset([aws_s3_bucket.data.arn]) &&
      data.aws_iam_policy_document.pipeline.statement[1].resources == toset(["${aws_s3_bucket.data.arn}/*"])
    )
    error_message = "The policy must apply to the pipeline's bucket only"
  }
}

run "an_endpoint_selects_the_emulator" {
  command = apply

  variables {
    aws_endpoint_url = "http://127.0.0.1:5001"
  }

  assert {
    condition     = local.emulated == true
    error_message = "Setting an endpoint must select the emulator"
  }
}
