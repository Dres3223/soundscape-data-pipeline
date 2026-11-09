"""Check whether the infrastructure exists, for the destroy-and-recreate cycle.

"present" also uploads a file, so destroy is tested on a bucket with data.

Usage (with the admin credentials in the environment):
    python scripts/check_infra.py moto present
    python scripts/check_infra.py moto absent
"""

import os
import re
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

PIPELINE_USER = "soundscape-pipeline"


def bucket_name(env: str) -> str:
    text = Path(f"infra/terraform/envs/{env}.tfvars").read_text()
    match = re.search(r'^bucket_name\s*=\s*"(.+)"', text, re.M)
    if match is None:
        sys.exit(f"bucket_name not found in the {env} settings")
    return match[1]


def exists(call, missing_code: str) -> bool:
    try:
        call()
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == missing_code:
            return False
        raise


def main() -> None:
    env, expected = sys.argv[1:3]
    style = "path" if os.environ.get("AWS_ENDPOINT_URL") else "auto"
    region = os.environ.get("AWS_REGION", "us-east-1")
    s3 = boto3.client(
        "s3", region_name=region, config=Config(s3={"addressing_style": style})
    )
    iam = boto3.client("iam", region_name=region)
    bucket = bucket_name(env)

    bucket_found = exists(lambda: s3.head_bucket(Bucket=bucket), "404")
    user_found = exists(lambda: iam.get_user(UserName=PIPELINE_USER), "NoSuchEntity")
    print(f">> bucket {bucket}: {bucket_found}; user: {user_found}")

    wanted = expected == "present"
    if (bucket_found, user_found) != (wanted, wanted):
        sys.exit(f"The infrastructure is not {expected}")
    if wanted:
        s3.put_object(Bucket=bucket, Key="cycle-check.txt", Body=b"data")


if __name__ == "__main__":
    main()
