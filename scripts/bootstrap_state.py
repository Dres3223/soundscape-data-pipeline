"""Create the bucket that holds Terraform's state, if it does not exist.

Terraform cannot store its state in a bucket it has yet to create, so this
one bucket is made here. Uses the admin credentials in the environment, and
AWS_ENDPOINT_URL when targeting an emulator. Safe to run repeatedly.

Usage:
    python scripts/bootstrap_state.py infra/terraform/envs/moto.backend.hcl
"""

import os
import re
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def setting(backend_file: str, name: str) -> str:
    match = re.search(rf'^{name}\s*=\s*"(.+)"', Path(backend_file).read_text(), re.M)
    if match is None:
        sys.exit(f"{name} not found in {backend_file}")
    return match[1]


def main() -> None:
    backend_file = sys.argv[1]
    bucket = setting(backend_file, "bucket")
    region = setting(backend_file, "region")
    style = "path" if os.environ.get("AWS_ENDPOINT_URL") else "auto"
    s3 = boto3.client(
        "s3", region_name=region, config=Config(s3={"addressing_style": style})
    )

    try:
        s3.head_bucket(Bucket=bucket)
        print(f">> State bucket {bucket} already exists")
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        options = {}
        if region != "us-east-1":  # AWS rejects the constraint for us-east-1
            options["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(Bucket=bucket, **options)
        print(f">> Created state bucket {bucket}")

    # Versioning makes a damaged state recoverable
    s3.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
            ]
        },
    )


if __name__ == "__main__":
    main()
