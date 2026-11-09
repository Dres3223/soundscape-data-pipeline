"""Give the pipeline's IAM user a new access key, or delete its keys.

Done here and not in Terraform so that the secret never reaches the state.
A new key replaces any previous one and is saved in .env.pipeline.<env>
(git-ignored, owner-only) with the settings the pipeline needs. Keys must be
deleted before Terraform can delete the user.

Usage (`make infra-apply` and `make infra-destroy` run it):
    python scripts/create_pipeline_key.py moto
    python scripts/create_pipeline_key.py moto --delete
"""

import json
import os
import subprocess
import sys

import boto3


def terraform_outputs() -> dict[str, str]:
    command = ["terraform", "-chdir=infra/terraform", "output", "-json"]
    raw = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return {name: item["value"] for name, item in json.loads(raw).items()}


def main() -> None:
    env = sys.argv[1]
    outputs = terraform_outputs()
    if "pipeline_user_name" not in outputs:
        return  # nothing has been created yet
    user = outputs["pipeline_user_name"]
    region = os.environ.get("AWS_REGION", "us-east-1")

    iam = boto3.client("iam", region_name=region)
    for old in iam.list_access_keys(UserName=user)["AccessKeyMetadata"]:
        iam.delete_access_key(UserName=user, AccessKeyId=old["AccessKeyId"])
    if "--delete" in sys.argv:
        print(f">> Deleted the access keys of {user}")
        return

    key = iam.create_access_key(UserName=user)["AccessKey"]

    path = f".env.pipeline.{env}"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(f"S3_ACCESS_KEY={key['AccessKeyId']}\n")
        file.write(f"S3_SECRET_KEY={key['SecretAccessKey']}\n")
        file.write(f"S3_BUCKET={outputs['bucket_name']}\n")
        file.write(f"S3_REGION={region}\n")
        # Empty means real AWS (see soundscape.config)
        file.write(f"S3_ENDPOINT_URL={os.environ.get('AWS_ENDPOINT_URL', '')}\n")
    print(f">> New access key for {user}; settings in {path}")


if __name__ == "__main__":
    main()
