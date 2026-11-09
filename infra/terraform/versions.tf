terraform {
  required_version = "~> 1.17"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
  }

  # Partial configuration: the details come from envs/<env>.backend.hcl,
  # so the emulator and AWS share this code
  backend "s3" {}
}
