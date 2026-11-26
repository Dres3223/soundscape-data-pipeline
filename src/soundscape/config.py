"""Pipeline configuration, read from environment variables (and .env)."""

import os
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_workers() -> int:
    """All cores but two, left for Postgres, S3 and the scheduler."""
    return max(1, (os.cpu_count() or 1) - 2)


class Settings(BaseSettings):
    """Typed settings: a missing or malformed variable fails at startup."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str

    # S3-compatible object storage (RustFS locally, AWS S3 later)
    s3_endpoint_url: str | None = "http://localhost:9000"  # None means AWS S3
    s3_access_key: str
    s3_secret_key: SecretStr
    s3_bucket: str = "soundscape"
    s3_region: str = "us-east-1"

    # Ingestion
    ingest_source_dir: Path = Path("data/raw/birdclef/train_soundscapes")
    ingest_source_name: str = "birdclef-2025"

    # Feature extraction: keep the native 32 kHz so sounds up to 16 kHz survive
    features_sample_rate: int = Field(default=32000, gt=0)
    features_n_mfcc: int = Field(default=20, gt=0)
    # Processes that analyze recordings at the same time
    features_workers: int = Field(default_factory=default_workers, gt=0)

    @field_validator("s3_endpoint_url", mode="before")
    @classmethod
    def empty_endpoint_means_aws(cls, value: str | None) -> str | None:
        """S3_ENDPOINT_URL= (empty) selects AWS S3 instead of a local endpoint."""
        return value or None
