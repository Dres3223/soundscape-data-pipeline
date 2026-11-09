"""Check that the pipeline's key can do what it should, and nothing else.

Reads .env.pipeline.<env>, so it acts with the pipeline's own identity.
Exits with an error if any permission differs from what is expected.

Usage (`make infra-check` runs it):
    python scripts/check_pipeline_permissions.py moto
"""

import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def read_env(path: str) -> dict[str, str]:
    lines = Path(path).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def main() -> None:
    settings = read_env(f".env.pipeline.{sys.argv[1]}")
    endpoint = settings["S3_ENDPOINT_URL"] or None
    bucket = settings["S3_BUCKET"]
    options = {
        "endpoint_url": endpoint,
        "region_name": settings["S3_REGION"],
        "aws_access_key_id": settings["S3_ACCESS_KEY"],
        "aws_secret_access_key": settings["S3_SECRET_KEY"],
        "config": Config(
            s3={"addressing_style": "path" if endpoint else "auto"},
            retries={"total_max_attempts": 1},
        ),
    }
    s3 = boto3.client("s3", **options)
    iam = boto3.client("iam", **options)
    key = "permission-check.txt"

    checks = [
        (
            "write to its bucket",
            True,
            lambda: s3.put_object(Bucket=bucket, Key=key, Body=b"check"),
        ),
        ("read from its bucket", True, lambda: s3.get_object(Bucket=bucket, Key=key)),
        ("list its bucket", True, lambda: s3.list_objects_v2(Bucket=bucket)),
        (
            "delete from its bucket",
            False,
            lambda: s3.delete_object(Bucket=bucket, Key=key),
        ),
        ("create a bucket", False, lambda: s3.create_bucket(Bucket="not-allowed")),
        ("list every bucket", False, s3.list_buckets),
        ("create an IAM user", False, lambda: iam.create_user(UserName="not-allowed")),
    ]

    failures = 0
    for label, expected, action in checks:
        try:
            action()
            allowed = True
        except ClientError:
            allowed = False
        correct = allowed == expected
        failures += not correct
        state = "allowed" if allowed else "denied"
        print(f"{'ok  ' if correct else 'FAIL'} {label}: {state}")

    if failures:
        sys.exit(f"{failures} permission(s) differ from what is expected")


if __name__ == "__main__":
    main()
