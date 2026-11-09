"""Extract audio features from the recordings registered in raw.recordings.

Usage:
    uv run python -m soundscape.features

Each recording is read from S3 into memory and summarised as one row of
numbers: MFCC (mean and std per coefficient), spectral centroid and
bandwidth, RMS energy, zero-crossing rate and duration. A damaged or empty
file is reported as failed instead of stopping the batch.

Results are written to S3 as Parquet (schema: docs/features_schema.md):
    features/site=<site>/month=<YYYY-MM>/features.parquet
    features_failed/failed.parquet
The run is incremental: only recordings without up-to-date features are
analyzed, and only the partitions they belong to are rewritten, keeping the
rows already there. Re-running with nothing new does no work.
"""

import io
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import librosa
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import soundfile as sf
from psycopg.rows import dict_row
from pydantic import ValidationError

from soundscape.config import Settings
from soundscape.storage import pg_connect, s3_client

log = logging.getLogger("soundscape.features")

# Raise it whenever the calculation changes: every recording is then redone
FEATURES_VERSION = 1

# Fixed schema: n_mfcc changes the length of the lists, not the columns
FEATURES_SCHEMA = pa.schema(
    [
        ("sha256", pa.string()),
        ("file_name", pa.string()),
        ("site_code", pa.string()),
        # Parquet has no seconds unit: "s" would be read back as "ms"
        ("recorded_at", pa.timestamp("ms")),
        ("duration_s", pa.float32()),
        ("mfcc_mean", pa.list_(pa.float32())),
        ("mfcc_std", pa.list_(pa.float32())),
        ("spectral_centroid_hz", pa.float32()),
        ("spectral_bandwidth_hz", pa.float32()),
        ("rms_mean", pa.float32()),
        ("zcr_mean", pa.float32()),
        ("sample_rate_hz", pa.int32()),
        ("n_mfcc", pa.int16()),
        ("features_version", pa.int16()),
        ("extracted_at", pa.timestamp("us", tz="UTC")),
    ]
)

FAILED_SCHEMA = pa.schema(
    [
        ("sha256", pa.string()),
        ("file_name", pa.string()),
        ("s3_key", pa.string()),
        ("error", pa.string()),
        ("extracted_at", pa.timestamp("us", tz="UTC")),
    ]
)

FAILED_KEY = "features_failed/failed.parquet"


@dataclass
class FeatureResult:
    """Outcome for one recording: its features, or why they could not be computed."""

    status: str  # "ok" or "failed"
    features: dict = field(default_factory=dict)
    error: str | None = None


def extract_features(audio: np.ndarray, sample_rate: int, n_mfcc: int) -> dict:
    """Summarise a mono signal as a dict of features (one entry per column)."""
    mfcc = librosa.feature.mfcc(y=audio, sr=sample_rate, n_mfcc=n_mfcc)
    centroid = librosa.feature.spectral_centroid(y=audio, sr=sample_rate)
    bandwidth = librosa.feature.spectral_bandwidth(y=audio, sr=sample_rate)
    return {
        "duration_s": round(len(audio) / sample_rate, 3),
        # One value per coefficient, averaged over time
        "mfcc_mean": mfcc.mean(axis=1).tolist(),
        "mfcc_std": mfcc.std(axis=1).tolist(),
        "spectral_centroid_hz": float(centroid.mean()),
        "spectral_bandwidth_hz": float(bandwidth.mean()),
        "rms_mean": float(librosa.feature.rms(y=audio).mean()),
        "zcr_mean": float(librosa.feature.zero_crossing_rate(audio).mean()),
    }


def analyze(data: bytes, sample_rate: int, n_mfcc: int) -> FeatureResult:
    """Decode an audio file held in memory and extract its features."""
    try:
        # Resamples only if the file's rate differs from sample_rate
        audio, _ = librosa.load(io.BytesIO(data), sr=sample_rate, mono=True)
    except sf.LibsndfileError as error:
        message = f"cannot decode audio: {error.error_string}"
        return FeatureResult("failed", error=message)

    if audio.size == 0:
        # A valid file with no samples decodes without error, so check it here
        return FeatureResult("failed", error="audio has no samples")
    return FeatureResult("ok", extract_features(audio, sample_rate, n_mfcc))


def partition_key(site_code: str, recorded_at: datetime) -> str:
    """Hive-style partition by site and month (~87 rows each on the full data)."""
    return f"features/site={site_code}/month={recorded_at:%Y-%m}/features.parquet"


def is_up_to_date(row: dict | None, sample_rate: int, n_mfcc: int) -> bool:
    """Whether stored features were computed with the current settings and code."""
    return (
        row is not None
        and row["sample_rate_hz"] == sample_rate
        and row["n_mfcc"] == n_mfcc
        and row["features_version"] == FEATURES_VERSION
    )


def read_existing_rows(s3, bucket: str) -> dict[str, dict]:
    """Stored features by recording; files with an older schema count as absent."""
    rows = {}
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix="features/"
    )
    for page in pages:
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            table = pq.read_table(io.BytesIO(body))
            if table.schema.equals(FEATURES_SCHEMA, check_metadata=False):
                rows.update({row["sha256"]: row for row in table.to_pylist()})
    return rows


def build_tables(
    results: list[tuple[dict, FeatureResult]],
    sample_rate: int,
    n_mfcc: int,
    extracted_at: datetime,
    kept_rows: Iterable[dict] = (),
) -> tuple[dict[str, pa.Table], pa.Table]:
    """Group results into one table per partition, plus a table of failures.

    Only partitions with a new result are returned; kept_rows fills those
    partitions with the rows that did not need recomputing.
    """
    partitions = defaultdict(list)
    failed = []
    for recording, result in results:
        if result.status == "ok":
            row = {
                "sha256": recording["sha256"],
                "file_name": recording["file_name"],
                "site_code": recording["site_code"],
                "recorded_at": recording["recorded_at"],
                **result.features,
                "sample_rate_hz": sample_rate,
                "n_mfcc": n_mfcc,
                "features_version": FEATURES_VERSION,
                "extracted_at": extracted_at,
            }
            key = partition_key(recording["site_code"], recording["recorded_at"])
            partitions[key].append(row)
        else:
            failed.append(
                {
                    "sha256": recording["sha256"],
                    "file_name": recording["file_name"],
                    "s3_key": recording["s3_key"],
                    "error": result.error,
                    "extracted_at": extracted_at,
                }
            )

    for row in kept_rows:
        key = partition_key(row["site_code"], row["recorded_at"])
        if key in partitions:
            partitions[key].append(row)

    tables = {
        key: pa.Table.from_pylist(
            sorted(rows, key=lambda row: (row["recorded_at"], row["file_name"])),
            schema=FEATURES_SCHEMA,
        )
        for key, rows in partitions.items()
    }
    return tables, pa.Table.from_pylist(failed, schema=FAILED_SCHEMA)


def put_parquet(s3, bucket: str, key: str, table: pa.Table) -> None:
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())


def run(settings: Settings) -> list[tuple[dict, FeatureResult]]:
    """Analyze the recordings without up-to-date features; write them to S3."""
    s3 = s3_client(settings)

    # raw.recordings is the catalog: only ingested files are processed (lineage)
    with pg_connect(settings, row_factory=dict_row) as conn:
        recordings = conn.execute(
            """
            SELECT sha256, file_name, site_code, recorded_at, s3_key
            FROM raw.recordings
            ORDER BY recorded_at, file_name
            """
        ).fetchall()

    sample_rate = settings.features_sample_rate
    n_mfcc = settings.features_n_mfcc
    existing = read_existing_rows(s3, settings.s3_bucket)
    pending, kept_rows = [], []
    for recording in recordings:
        row = existing.get(recording["sha256"])
        if is_up_to_date(row, sample_rate, n_mfcc):
            kept_rows.append(row)
        else:
            pending.append(recording)
    log.info("Up to date: %d; to analyze: %d", len(kept_rows), len(pending))

    results = []
    for recording in pending:
        body = s3.get_object(Bucket=settings.s3_bucket, Key=recording["s3_key"])
        result = analyze(body["Body"].read(), sample_rate, n_mfcc)
        if result.status == "ok":
            log.info("Extracted %s", recording["file_name"])
        else:
            log.warning("Failed %s: %s", recording["file_name"], result.error)
        results.append((recording, result))

    tables, failed = build_tables(
        results,
        sample_rate,
        n_mfcc,
        extracted_at=datetime.now(UTC),
        kept_rows=kept_rows,
    )
    for key, table in tables.items():
        put_parquet(s3, settings.s3_bucket, key, table)
        log.info("Wrote %d rows to s3://%s/%s", table.num_rows, settings.s3_bucket, key)
    # Always written, even empty, so the latest run's failures are what it shows
    put_parquet(s3, settings.s3_bucket, FAILED_KEY, failed)
    return results


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
            field_name = ".".join(str(part) for part in problem["loc"])
            log.error("Invalid configuration for %s: %s", field_name, problem["msg"])
        raise SystemExit(1) from None

    results = run(settings)
    ok = sum(result.status == "ok" for _, result in results)
    log.info("Summary: ok=%d failed=%d", ok, len(results) - ok)


if __name__ == "__main__":
    main()
