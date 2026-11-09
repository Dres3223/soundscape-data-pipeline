"""Copy the objects of the local bucket to another one, keeping their paths.

The catalog (raw.recordings) stores each object's path, so a bucket filled this
way can replace the original. Objects already there with the same size are
skipped, so the command can be re-run after a failure.

Usage:
    uv run python -m soundscape.sync_storage moto
"""

import logging
import sys
from pathlib import Path

from pydantic import SecretStr

from soundscape.config import Settings
from soundscape.storage import s3_client

log = logging.getLogger("soundscape.sync_storage")


def list_sizes(s3, bucket: str) -> dict[str, int]:
    """Every object in the bucket with its size (S3 returns 1,000 per page)."""
    sizes = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        sizes.update({obj["Key"]: obj["Size"] for obj in page.get("Contents", [])})
    return sizes


def objects_to_copy(source: dict[str, int], target: dict[str, int]) -> list[str]:
    """Keys missing from the target, or with a different size there."""
    return sorted(key for key, size in source.items() if target.get(key) != size)


def sync(source, source_bucket: str, target, target_bucket: str) -> dict[str, int]:
    source_sizes = list_sizes(source, source_bucket)
    keys = objects_to_copy(source_sizes, list_sizes(target, target_bucket))
    for key in keys:
        body = source.get_object(Bucket=source_bucket, Key=key)["Body"].read()
        target.put_object(Bucket=target_bucket, Key=key, Body=body)
    return {"copied": len(keys), "skipped": len(source_sizes) - len(keys)}


def target_settings(local: Settings, env_file: Path) -> Settings:
    lines = env_file.read_text().splitlines()
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    return local.model_copy(
        update={
            "s3_endpoint_url": values["S3_ENDPOINT_URL"] or None,
            "s3_access_key": values["S3_ACCESS_KEY"],
            "s3_secret_key": SecretStr(values["S3_SECRET_KEY"]),
            "s3_bucket": values["S3_BUCKET"],
            "s3_region": values["S3_REGION"],
        }
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("botocore").setLevel(logging.WARNING)

    local = Settings()
    target = target_settings(local, Path(f".env.pipeline.{sys.argv[1]}"))
    counts = sync(
        s3_client(local), local.s3_bucket, s3_client(target), target.s3_bucket
    )
    log.info(
        "Copied to %s: copied=%d skipped=%d",
        target.s3_bucket,
        counts["copied"],
        counts["skipped"],
    )


if __name__ == "__main__":
    main()
