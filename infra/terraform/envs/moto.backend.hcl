# Terraform state in the emulator
bucket       = "soundscape-tfstate-moto"
key          = "soundscape/terraform.tfstate"
region       = "us-east-1"
encrypt      = true
use_lockfile = true

use_path_style              = true
skip_credentials_validation = true
skip_metadata_api_check     = true
skip_requesting_account_id  = true
endpoints                   = { s3 = "http://127.0.0.1:5001" }
