"""Ingest raw recordings: upload audio files to S3 and register them in Postgres.

Usage:
    uv run python -m soundscape.ingest

Idempotent: a file whose SHA-256 is already registered is skipped, so the
command can be re-run safely after a failure.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path

import psycopg
import soundfile as sf
from botocore.exceptions import ClientError
from pydantic import ValidationError

from soundscape.config import Settings
from soundscape.storage import pg_connect, s3_client

log = logging.getLogger("soundscape.ingest")

# SITE_YYYYMMDD_HHMMSS.ogg, e.g. H02_20230422_014500.ogg or O201_20230512_011500.ogg
FILE_NAME_PATTERN = re.compile(r"^(?P<site>[A-Z]+\d+)_(?P<stamp>\d{8}_\d{6})\.ogg$")


@dataclass(frozen=True)
class RecordingName:
    """What the file name tells us about a recording."""

    site_code: str
    recorded_at: datetime


def parse_file_name(file_name: str) -> RecordingName:
    """Extract site and timestamp from a file name; raise ValueError if invalid."""
    match = FILE_NAME_PATTERN.match(file_name)
    if match is None:
        raise ValueError("name does not match SITE_YYYYMMDD_HHMMSS.ogg")
    try:
        # strptime also rejects impossible dates such as 20230231
        recorded_at = datetime.strptime(match["stamp"], "%Y%m%d_%H%M%S")
    except ValueError as error:
        raise ValueError(f"invalid date or time ({error})") from None
    return RecordingName(site_code=match["site"], recorded_at=recorded_at)


def build_s3_key(source: str, name: RecordingName, file_name: str) -> str:
    """Hive-style key, so query engines can prune by site and date."""
    return (
        f"raw/{source}/site={name.site_code}"
        f"/date={name.recorded_at:%Y-%m-%d}/{file_name}"
    )


def sha256_of(path: Path) -> str:
    """Content fingerprint, read in chunks so large files do not fill memory."""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def ensure_bucket(s3, bucket: str) -> None:
    """Create the bucket only if it is really missing."""
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as error:
        status = error.response["ResponseMetadata"]["HTTPStatusCode"]
        if status == 404:
            log.info("Creating bucket %s", bucket)
            s3.create_bucket(Bucket=bucket)
        elif status != 403:
            raise
        # 403: it exists but this key may not inspect it (Terraform manages it).
        # If the key cannot write there either, the first upload will say so.


def ensure_schema(conn: psycopg.Connection) -> None:
    sql = files("soundscape").joinpath("sql/001_raw_recordings.sql").read_text()
    conn.execute(sql)


def run(settings: Settings) -> dict[str, int]:
    counts = {"loaded": 0, "skipped": 0, "rejected": 0}
    source_dir = settings.ingest_source_dir
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source folder not found: {source_dir}")

    s3 = s3_client(settings)
    ensure_bucket(s3, settings.s3_bucket)

    # autocommit: each inserted row is committed on its own
    with pg_connect(settings, autocommit=True) as conn:
        ensure_schema(conn)
        rows = conn.execute("SELECT sha256, file_name FROM raw.recordings").fetchall()
        known_hashes = {sha for sha, _ in rows}
        known_names = {name for _, name in rows}

        for path in sorted(source_dir.glob("*.ogg")):
            digest = sha256_of(path)
            if digest in known_hashes:
                counts["skipped"] += 1
                continue

            if path.name in known_names:
                # Same name, different content: never overwrite raw data silently
                log.warning("Rejected %s: content changed since ingestion", path.name)
                counts["rejected"] += 1
                continue

            try:
                name = parse_file_name(path.name)
            except ValueError as error:
                log.warning("Rejected %s: %s", path.name, error)
                counts["rejected"] += 1
                continue

            try:
                info = sf.info(path)
            except sf.LibsndfileError as error:
                # A damaged file must not stop the batch, nor reach the raw layer
                log.warning(
                    "Rejected %s: cannot read audio (%s)", path.name, error.error_string
                )
                counts["rejected"] += 1
                continue

            key = build_s3_key(settings.ingest_source_name, name, path.name)

            # Upload first, then register: the row is the "done" marker
            s3.upload_file(str(path), settings.s3_bucket, key)
            conn.execute(
                """
                INSERT INTO raw.recordings (
                    sha256, file_name, site_code, recorded_at, duration_s,
                    sample_rate_hz, channels, size_bytes, s3_key, source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sha256) DO NOTHING
                """,
                (
                    digest,
                    path.name,
                    name.site_code,
                    name.recorded_at,
                    round(info.duration, 3),
                    info.samplerate,
                    info.channels,
                    path.stat().st_size,
                    key,
                    settings.ingest_source_name,
                ),
            )
            known_hashes.add(digest)
            known_names.add(path.name)
            counts["loaded"] += 1
            log.info("Loaded %s -> s3://%s/%s", path.name, settings.s3_bucket, key)

    return counts


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # boto3 is chatty at INFO level
    logging.getLogger("botocore").setLevel(logging.WARNING)

    try:
        settings = Settings()
    except ValidationError as error:
        # Report which settings are wrong without echoing their values (secrets)
        for problem in error.errors(include_input=False, include_url=False):
            field = ".".join(str(part) for part in problem["loc"])
            log.error("Invalid configuration for %s: %s", field, problem["msg"])
        raise SystemExit(1) from None

    counts = run(settings)
    log.info(
        "Summary: loaded=%d skipped=%d rejected=%d",
        counts["loaded"],
        counts["skipped"],
        counts["rejected"],
    )


if __name__ == "__main__":
    main()
