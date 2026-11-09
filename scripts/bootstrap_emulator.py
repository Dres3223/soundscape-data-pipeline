"""Create the admin user of a fresh AWS emulator and save its credentials.

Moto starts empty and accepts exactly 3 requests without credentials
(INITIAL_NO_AUTH_ACTION_COUNT in docker-compose.yml): the 3 calls below.
From then on every request needs valid keys, so permissions really apply.

Usage (`make emulator` runs it right after starting a fresh emulator):
    uv run python scripts/bootstrap_emulator.py
"""

import json
import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ENV_FILE = Path(".env.moto")
ADMIN_USER = "terraform-admin"
ADMIN_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
}


def main() -> None:
    endpoint = f"http://127.0.0.1:{os.environ.get('MOTO_PORT', '5001')}"
    iam = boto3.client(
        "iam",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="bootstrap",
        aws_secret_access_key="bootstrap",
        # A retry would spend one of the 3 requests without credentials
        config=Config(retries={"total_max_attempts": 1}),
    )

    try:
        iam.create_user(UserName=ADMIN_USER)
        iam.put_user_policy(
            UserName=ADMIN_USER,
            PolicyName="administrator",
            PolicyDocument=json.dumps(ADMIN_POLICY),
        )
        key = iam.create_access_key(UserName=ADMIN_USER)["AccessKey"]
    except ClientError as error:
        code = error.response["Error"]["Code"]
        sys.exit(f"Cannot create the admin user ({code}). Is the emulator fresh?")

    # Owner-only permissions from the moment the file exists
    descriptor = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(f"AWS_ACCESS_KEY_ID={key['AccessKeyId']}\n")
        file.write(f"AWS_SECRET_ACCESS_KEY={key['SecretAccessKey']}\n")
        file.write("AWS_REGION=us-east-1\n")
    print(f">> Admin user {ADMIN_USER} created; credentials in {ENV_FILE}")


if __name__ == "__main__":
    main()
