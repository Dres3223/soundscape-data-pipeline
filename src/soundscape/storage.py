"""Clients for the pipeline's storage: S3 object storage and PostgreSQL."""

import boto3
import psycopg
from botocore.config import Config

from soundscape.config import Settings


def s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        # RustFS and Moto only support path-style addressing (see ADR 0001);
        # on real AWS (no endpoint) boto3 chooses the right style
        config=Config(
            s3={"addressing_style": "path" if settings.s3_endpoint_url else "auto"}
        ),
    )


def pg_connect(settings: Settings, **kwargs) -> psycopg.Connection:
    """Open a Postgres connection; kwargs go to psycopg (autocommit, row_factory)."""
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        dbname=settings.postgres_db,
        **kwargs,
    )
