"""Load features and detections from S3 (Parquet) into Postgres.

Usage:
    uv run python -m soundscape.load

Features go to raw.audio_features with an upsert keyed by sha256: a new
recording is inserted, a recording whose features were re-extracted (newer
extracted_at) is updated, anything else is left as it is.

Detections go to raw.detection_recordings and raw.bird_detections: a recording
analyzed again (newer detected_at) has its detections replaced as a whole.
Re-running gives the same tables, so the load is idempotent.
"""

import io
import logging
from importlib.resources import files

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg import sql
from pydantic import ValidationError

from soundscape import detections
from soundscape.config import Settings
from soundscape.features import FEATURES_SCHEMA
from soundscape.storage import pg_connect, s3_client

log = logging.getLogger("soundscape.load")

FEATURES_PREFIX = "features/"
COLUMNS = FEATURES_SCHEMA.names  # same columns, same order as the Parquet files


def list_feature_keys(s3, bucket: str, prefix: str = FEATURES_PREFIX) -> list[str]:
    """Every Parquet file under the prefix (paginated: S3 returns 1,000 per page)."""
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix
    ):
        keys += [obj["Key"] for obj in page.get("Contents", [])]
    return sorted(key for key in keys if key.endswith(".parquet"))


def read_features(s3, bucket: str, keys: list[str]) -> pa.Table:
    """Read and concatenate the files; refuse any file with a different schema."""
    tables = []
    for key in keys:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        table = pq.read_table(io.BytesIO(body))
        if not table.schema.equals(FEATURES_SCHEMA, check_metadata=False):
            raise ValueError(f"{key} does not match FEATURES_SCHEMA")
        tables.append(table)
    return pa.concat_tables(tables) if tables else FEATURES_SCHEMA.empty_table()


def ensure_schema(conn: psycopg.Connection) -> None:
    for name in ("002_raw_audio_features.sql", "003_raw_bird_detections.sql"):
        conn.execute(files("soundscape").joinpath("sql", name).read_text())


def read_detections(s3, bucket: str) -> tuple[pa.Table, pa.Table]:
    """Every recordings and detections file; refuse any with a different schema."""
    tables = {}
    for file_name, schema in (
        (detections.RECORDINGS_FILE, detections.RECORDINGS_SCHEMA),
        (detections.DETECTIONS_FILE, detections.DETECTIONS_SCHEMA),
    ):
        parts = []
        for key in detections.list_keys(s3, bucket, file_name):
            table = detections.read_parquet(s3, bucket, key)
            if not table.schema.equals(schema, check_metadata=False):
                raise ValueError(f"{key} does not match the detections schema")
            parts.append(table)
        tables[file_name] = pa.concat_tables(parts) if parts else schema.empty_table()
    return tables[detections.RECORDINGS_FILE], tables[detections.DETECTIONS_FILE]


def copy_rows(conn: psycopg.Connection, target: str, table: pa.Table) -> None:
    names = table.schema.names
    copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(target), sql.SQL(", ").join(map(sql.Identifier, names))
    )
    with conn.cursor().copy(copy_sql) as copy:
        for row in table.to_pylist():
            copy.write_row([row[name] for name in names])


def upsert_detections(
    conn: psycopg.Connection, recordings: pa.Table, found: pa.Table
) -> dict[str, int]:
    """Replace the detections of every recording analyzed since the last load."""
    with conn.transaction():
        conn.execute(
            "CREATE TEMP TABLE recordings_batch"
            " (LIKE raw.detection_recordings INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        conn.execute(
            "CREATE TEMP TABLE detections_batch"
            " (LIKE raw.bird_detections) ON COMMIT DROP"
        )
        copy_rows(conn, "recordings_batch", recordings)
        copy_rows(conn, "detections_batch", found)

        # Recordings that are new or were analyzed again
        conn.execute(
            """
            CREATE TEMP TABLE changed ON COMMIT DROP AS
            SELECT batch.sha256
            FROM recordings_batch AS batch
            LEFT JOIN raw.detection_recordings AS stored USING (sha256)
            WHERE stored.sha256 IS NULL OR batch.detected_at > stored.detected_at
            """
        )
        # Deleting the recording row also deletes its detections (cascade)
        conn.execute(
            "DELETE FROM raw.detection_recordings WHERE sha256 IN (TABLE changed)"
        )
        recording_columns = sql.SQL(", ").join(
            map(sql.Identifier, detections.RECORDINGS_SCHEMA.names)
        )
        conn.execute(
            sql.SQL(
                "INSERT INTO raw.detection_recordings ({0})"
                " SELECT {0} FROM recordings_batch WHERE sha256 IN (TABLE changed)"
            ).format(recording_columns)
        )
        detection_columns = sql.SQL(", ").join(
            map(sql.Identifier, detections.DETECTIONS_SCHEMA.names)
        )
        inserted = conn.execute(
            sql.SQL(
                "INSERT INTO raw.bird_detections ({0})"
                " SELECT {0} FROM detections_batch WHERE sha256 IN (TABLE changed)"
            ).format(detection_columns)
        ).rowcount
        changed = conn.execute("SELECT count(*) FROM changed").fetchone()[0]
    return {
        "recordings": recordings.num_rows,
        "replaced": changed,
        "detections": inserted,
    }


def upsert_features(conn: psycopg.Connection, table: pa.Table) -> dict[str, int]:
    """Bulk upsert in one transaction: all rows are written, or none."""
    columns = sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
    updates = sql.SQL(", ").join(
        sql.SQL("{0} = excluded.{0}").format(sql.Identifier(name))
        for name in COLUMNS
        if name != "sha256"
    )

    with conn.transaction():
        # 1. COPY into a temporary table: the fastest way to insert many rows
        conn.execute(
            "CREATE TEMP TABLE audio_features_batch"
            " (LIKE raw.audio_features INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        copy_sql = sql.SQL("COPY audio_features_batch ({}) FROM STDIN").format(columns)
        with conn.cursor().copy(copy_sql) as copy:
            for row in table.to_pylist():
                copy.write_row([row[name] for name in COLUMNS])

        # 2. One INSERT ... ON CONFLICT moves the batch into the real table.
        # Only a newer extraction overwrites a row, so an old file never wins.
        # xmax = 0 is true for rows this statement inserted, false for updated ones.
        upsert = sql.SQL(
            """
            INSERT INTO raw.audio_features ({columns})
            SELECT DISTINCT ON (sha256) {columns}
            FROM audio_features_batch
            ORDER BY sha256, extracted_at DESC
            ON CONFLICT (sha256) DO UPDATE
            SET {updates}, loaded_at = now()
            WHERE excluded.extracted_at > raw.audio_features.extracted_at
            RETURNING (xmax = 0) AS inserted
            """
        ).format(columns=columns, updates=updates)
        written = [inserted for (inserted,) in conn.execute(upsert).fetchall()]

    inserted = sum(written)
    return {
        "read": table.num_rows,
        "inserted": inserted,
        "updated": len(written) - inserted,
        "unchanged": table.num_rows - len(written),
    }


def run(settings: Settings) -> dict[str, dict[str, int]]:
    s3 = s3_client(settings)
    keys = list_feature_keys(s3, settings.s3_bucket)
    table = read_features(s3, settings.s3_bucket, keys)
    log.info("Read %d rows from %d files", table.num_rows, len(keys))

    # autocommit: ensure_schema commits on its own, and conn.transaction() in
    # upsert_features is then a real transaction instead of a nested savepoint
    with pg_connect(settings, autocommit=True) as conn:
        ensure_schema(conn)
        counts = upsert_features(conn, table)
        analyzed, found = read_detections(s3, settings.s3_bucket)
        detection_counts = upsert_detections(conn, analyzed, found)
    log.info(
        "Loaded into raw.audio_features: inserted=%d updated=%d unchanged=%d",
        counts["inserted"],
        counts["updated"],
        counts["unchanged"],
    )
    log.info(
        "Loaded detections: %d recordings re-analyzed, %d detections written",
        detection_counts["replaced"],
        detection_counts["detections"],
    )
    return {"features": counts, "detections": detection_counts}


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

    run(settings)


if __name__ == "__main__":
    main()
