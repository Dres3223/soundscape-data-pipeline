"""Detect bird species in the recordings registered in raw.recordings.

Usage:
    uv run python -m soundscape.detections

BirdNET V2.4 (Kahl et al. 2021) splits each recording into 3-second segments
and scores every species it knows from 0 to 1. Every score of at least
MIN_CONFIDENCE is kept, one row per recording, segment and species; dbt then
decides with the thresholds in a seed which ones count (schema and limits:
docs/detections_schema.md). The scores are not probabilities; how often they
agree with published labels at El Silencio: docs/validation.md.

Each detection also carries the score of BirdNET's geographic model for that
species at the reserve in that week of the year, so dbt can drop species that
are implausible there.

Results are written to S3 as Parquet, partitioned like the features:
    detections/site=<site>/month=<YYYY-MM>/detections.parquet  (one row per detection)
    detections/site=<site>/month=<YYYY-MM>/recordings.parquet  (one row per recording)
The recordings file lists every recording analyzed, with or without detections,
so a recording with no birds is told apart from one never analyzed. The run is
incremental, like soundscape.features, and writes every CHECKPOINT_SIZE
recordings, so a run that stops halfway keeps what it did.
"""

import io
import logging
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from psycopg.rows import dict_row
from pydantic import ValidationError

from soundscape.config import Settings
from soundscape.storage import pg_connect, s3_client

log = logging.getLogger("soundscape.detections")

# Raise it whenever the calculation changes: every recording is then redone
DETECTIONS_VERSION = 1
MODEL_VERSION = "2.4"
MIN_CONFIDENCE = 0.1  # lowest score stored; dbt applies the real threshold
# El Silencio reserve, Yondó (BirdCLEF 2025 recording_location.txt); one point
# for every site, enough for the geographic model's coarse grid
LATITUDE, LONGITUDE = 6.76, -74.21
BATCH_SIZE = 100  # recordings written to disk and analyzed together
CHECKPOINT_SIZE = 500  # recordings analyzed between two writes to S3

PREFIX = "detections/"
DETECTIONS_FILE = "detections.parquet"
RECORDINGS_FILE = "recordings.parquet"

DETECTIONS_SCHEMA = pa.schema(
    [
        ("sha256", pa.string()),
        ("file_name", pa.string()),
        ("site_code", pa.string()),
        ("recorded_at", pa.timestamp("us")),
        ("start_s", pa.float32()),
        ("end_s", pa.float32()),
        ("scientific_name", pa.string()),
        ("common_name", pa.string()),
        ("confidence", pa.float32()),
        ("geo_score", pa.float32()),  # null: species unknown to the geo model
        ("detected_at", pa.timestamp("us", tz="UTC")),
    ]
)
RECORDINGS_SCHEMA = pa.schema(
    [
        ("sha256", pa.string()),
        ("file_name", pa.string()),
        ("site_code", pa.string()),
        ("recorded_at", pa.timestamp("us")),
        ("status", pa.string()),  # ok | failed
        ("error", pa.string()),
        ("n_detections", pa.int32()),
        ("week", pa.int8()),
        ("model_version", pa.string()),
        ("min_confidence", pa.float32()),
        ("detections_version", pa.int16()),
        ("detected_at", pa.timestamp("us", tz="UTC")),
    ]
)


def partition_prefix(site_code: str, recorded_at: datetime) -> str:
    return f"{PREFIX}site={site_code}/month={recorded_at:%Y-%m}/"


def birdnet_week(day: datetime) -> int:
    """BirdNET's week of the year: 4 per month, 1-48."""
    return (day.month - 1) * 4 + min((day.day - 1) // 7, 3) + 1


def split_species(label: str) -> tuple[str, str]:
    """'Sporophila funerea_Thick-billed Seed-Finch' -> scientific, common name."""
    scientific, _, common = label.partition("_")
    return scientific, common


def is_up_to_date(row: dict | None) -> bool:
    """Whether a recording was analyzed with the current model and code."""
    return (
        row is not None
        and row["status"] == "ok"
        and row["model_version"] == MODEL_VERSION
        and row["detections_version"] == DETECTIONS_VERSION
    )


def geo_scores(weeks: Iterable[int]) -> dict[int, dict[str, float]]:
    """Score of the geographic model per week and species label."""
    import birdnet

    model = birdnet.load("geo", MODEL_VERSION, "tf", library="litert")
    scores = {}
    for week in sorted(set(weeks)):
        result = model.predict(LATITUDE, LONGITUDE, week=week, min_confidence=0.0)
        table = result.to_dataframe()
        scores[week] = dict(
            zip(table["species_name"], table["confidence"], strict=True)
        )
    return scores


def detect(paths: list[Path]) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Run BirdNET on audio files: detections per file name, and failures."""
    import birdnet

    model = birdnet.load("acoustic", MODEL_VERSION, "tf", library="litert")
    result = model.predict(
        paths, top_k=None, default_confidence_threshold=MIN_CONFIDENCE
    )
    found = defaultdict(list)
    for row in result.to_dataframe().itertuples(index=False):
        found[Path(row.input).name].append(
            {
                "start_s": float(row.start_time),
                "end_s": float(row.end_time),
                "label": row.species_name,
                "confidence": float(row.confidence),
            }
        )
    # Indices into result.inputs, which BirdNET de-duplicates and sorts: not
    # positions in `paths`
    failed = {
        Path(str(result.inputs[index])).name: "BirdNET could not read the audio"
        for index in result.unprocessable_inputs
    }
    return found, failed


def build_tables(
    recordings: list[dict],
    found: dict[str, list[dict]],
    failed: dict[str, str],
    geo: dict[int, dict[str, float]],
    detected_at: datetime,
    kept: dict[str, tuple[dict, list[dict]]] | None = None,
) -> dict[str, pa.Table]:
    """One detections table and one recordings table per touched partition.

    kept maps a partition prefix to the rows that did not need recomputing; it
    only fills partitions with a new result.
    """
    detections, analyzed = defaultdict(list), defaultdict(list)
    for recording in recordings:
        prefix = partition_prefix(recording["site_code"], recording["recorded_at"])
        identity = {
            key: recording[key]
            for key in ("sha256", "file_name", "site_code", "recorded_at")
        }
        week = birdnet_week(recording["recorded_at"])
        rows = (
            []
            if recording["file_name"] in failed
            else found.get(recording["file_name"], [])
        )
        for row in rows:
            scientific, common = split_species(row["label"])
            detections[prefix].append(
                {
                    **identity,
                    "start_s": row["start_s"],
                    "end_s": row["end_s"],
                    "scientific_name": scientific,
                    "common_name": common,
                    "confidence": row["confidence"],
                    "geo_score": geo.get(week, {}).get(row["label"]),
                    "detected_at": detected_at,
                }
            )
        analyzed[prefix].append(
            {
                **identity,
                "status": "failed" if recording["file_name"] in failed else "ok",
                "error": failed.get(recording["file_name"]),
                "n_detections": len(rows),
                "week": week,
                "model_version": MODEL_VERSION,
                "min_confidence": MIN_CONFIDENCE,
                "detections_version": DETECTIONS_VERSION,
                "detected_at": detected_at,
            }
        )

    for prefix, (kept_recordings, kept_detections) in (kept or {}).items():
        if prefix in analyzed:
            analyzed[prefix] += kept_recordings
            detections[prefix] += kept_detections

    def ordered(rows: list[dict], *keys: str) -> list[dict]:
        return sorted(rows, key=lambda row: tuple(row[key] for key in keys))

    tables = {}
    for prefix, rows in analyzed.items():
        tables[prefix + RECORDINGS_FILE] = pa.Table.from_pylist(
            ordered(rows, "recorded_at", "file_name"), schema=RECORDINGS_SCHEMA
        )
        tables[prefix + DETECTIONS_FILE] = pa.Table.from_pylist(
            ordered(
                detections[prefix],
                "recorded_at",
                "file_name",
                "start_s",
                "scientific_name",
            ),
            schema=DETECTIONS_SCHEMA,
        )
    return tables


def read_parquet(s3, bucket: str, key: str) -> pa.Table:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pq.read_table(io.BytesIO(body))


def list_keys(s3, bucket: str, file_name: str) -> list[str]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=PREFIX
    ):
        keys += [obj["Key"] for obj in page.get("Contents", [])]
    return sorted(key for key in keys if key.endswith("/" + file_name))


def read_existing(s3, bucket: str) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Stored recordings by sha256 and stored detections by sha256."""
    recordings, detections = {}, defaultdict(list)
    for key in list_keys(s3, bucket, RECORDINGS_FILE):
        table = read_parquet(s3, bucket, key)
        if table.schema.equals(RECORDINGS_SCHEMA, check_metadata=False):
            recordings.update({row["sha256"]: row for row in table.to_pylist()})
    for key in list_keys(s3, bucket, DETECTIONS_FILE):
        table = read_parquet(s3, bucket, key)
        if table.schema.equals(DETECTIONS_SCHEMA, check_metadata=False):
            for row in table.to_pylist():
                detections[row["sha256"]].append(row)
    return recordings, detections


def put_parquet(s3, bucket: str, key: str, table: pa.Table) -> None:
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())


def run(settings: Settings) -> dict[str, int]:
    """Analyze the recordings without up-to-date detections; write them to S3."""
    s3 = s3_client(settings)
    with pg_connect(settings, row_factory=dict_row) as conn:
        recordings = conn.execute(
            """
            SELECT sha256, file_name, site_code, recorded_at, s3_key
            FROM raw.recordings
            ORDER BY recorded_at, file_name
            """
        ).fetchall()

    stored, stored_detections = read_existing(s3, settings.s3_bucket)
    pending, kept = [], defaultdict(lambda: ([], []))
    for recording in recordings:
        row = stored.get(recording["sha256"])
        if is_up_to_date(row):
            prefix = partition_prefix(recording["site_code"], recording["recorded_at"])
            kept[prefix][0].append(row)
            kept[prefix][1].extend(stored_detections.get(recording["sha256"], []))
        else:
            pending.append(recording)
    log.info(
        "Up to date: %d; to analyze: %d",
        sum(len(rows) for rows, _ in kept.values()),
        len(pending),
    )
    if not pending:
        return {"analyzed": 0, "failed": 0, "detections": 0}

    # By partition, so each checkpoint rewrites few files
    pending.sort(key=lambda r: (r["site_code"], r["recorded_at"], r["file_name"]))
    geo = geo_scores(birdnet_week(r["recorded_at"]) for r in pending)
    counts = {"analyzed": 0, "failed": 0, "detections": 0}
    with tempfile.TemporaryDirectory() as folder:
        for start in range(0, len(pending), CHECKPOINT_SIZE):
            part = pending[start : start + CHECKPOINT_SIZE]
            found, failed = {}, {}
            for batch_start in range(0, len(part), BATCH_SIZE):
                batch = part[batch_start : batch_start + BATCH_SIZE]
                paths = []
                for recording in batch:
                    path = Path(folder) / recording["file_name"]
                    body = s3.get_object(
                        Bucket=settings.s3_bucket, Key=recording["s3_key"]
                    )
                    path.write_bytes(body["Body"].read())
                    paths.append(path)
                batch_found, batch_failed = detect(paths)
                found.update(batch_found)
                failed.update(batch_failed)
                for path in paths:
                    path.unlink()

            tables = build_tables(part, found, failed, geo, datetime.now(UTC), kept)
            for key, table in tables.items():
                put_parquet(s3, settings.s3_bucket, key, table)
            # The partitions just written now hold every row the next
            # checkpoint must keep
            for key in tables:
                prefix = key.rsplit("/", 1)[0] + "/"
                kept[prefix] = (
                    tables[prefix + RECORDINGS_FILE].to_pylist(),
                    tables[prefix + DETECTIONS_FILE].to_pylist(),
                )
            for name in failed:
                log.warning("Failed %s: %s", name, failed[name])
            counts["analyzed"] += len(part) - len(failed)
            counts["failed"] += len(failed)
            counts["detections"] += sum(
                len(found.get(r["file_name"], []))
                for r in part
                if r["file_name"] not in failed
            )
            log.info(
                "Analyzed %d of %d recordings (%d partitions written)",
                start + len(part),
                len(pending),
                len(tables) // 2,
            )
    return counts


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("botocore").setLevel(logging.WARNING)

    try:
        settings = Settings()
    except ValidationError as error:
        for problem in error.errors(include_input=False, include_url=False):
            field_name = ".".join(str(part) for part in problem["loc"])
            log.error("Invalid configuration for %s: %s", field_name, problem["msg"])
        raise SystemExit(1) from None

    counts = run(settings)
    log.info(
        "Summary: analyzed=%d failed=%d detections=%d",
        counts["analyzed"],
        counts["failed"],
        counts["detections"],
    )


if __name__ == "__main__":
    main()
