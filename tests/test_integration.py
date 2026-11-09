"""End-to-end tests against the Docker services (PostgreSQL and RustFS).

They use their own database and bucket, so they never touch the real data,
and are skipped when the services are not running (docker compose up -d).
Run only the fast tests with: uv run pytest -m "not integration"
"""

import io
from datetime import UTC, datetime

import numpy as np
import psycopg
import pyarrow.parquet as pq
import pytest
import soundfile as sf
from botocore.exceptions import BotoCoreError, ClientError
from psycopg import sql

from soundscape import features, ingest, load
from soundscape.config import Settings
from soundscape.storage import pg_connect, s3_client

pytestmark = pytest.mark.integration

TEST_DB = "soundscape_test"
TEST_BUCKET = "soundscape-test"
SAMPLE_RATE = 32000
# Two sites and two months, so features land in two partitions
FILE_NAMES = ["T01_20230422_014500.ogg", "T02_20230512_060000.ogg"]


def write_tone(path, frequency_hz: float) -> None:
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE  # one second
    sf.write(path, 0.5 * np.sin(2 * np.pi * frequency_hz * t), SAMPLE_RATE)


@pytest.fixture
def settings(tmp_path):
    """Settings pointing at an empty test database, bucket and source folder."""
    base = Settings()
    try:
        with pg_connect(base, autocommit=True, connect_timeout=2) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)
            ).fetchone()
            if not exists:
                conn.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB))
                )
        s3_client(base).list_buckets()
    except (psycopg.OperationalError, BotoCoreError, ClientError) as error:
        pytest.skip(f"services not available: {error}")

    test = base.model_copy(
        update={
            "postgres_db": TEST_DB,
            "s3_bucket": TEST_BUCKET,
            "ingest_source_dir": tmp_path,
        }
    )

    # Start from a clean state: no tables, no objects
    with pg_connect(test, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS raw CASCADE")
    s3 = s3_client(test)
    ingest.ensure_bucket(s3, TEST_BUCKET)
    for obj in s3.list_objects_v2(Bucket=TEST_BUCKET).get("Contents", []):
        s3.delete_object(Bucket=TEST_BUCKET, Key=obj["Key"])

    for i, name in enumerate(FILE_NAMES):
        write_tone(tmp_path / name, frequency_hz=1000 * (i + 1))
    return test


def object_keys(settings: Settings, prefix: str = "") -> list[str]:
    s3 = s3_client(settings)
    response = s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix=prefix)
    return sorted(obj["Key"] for obj in response.get("Contents", []))


def test_ingest_is_idempotent(settings):
    first = ingest.run(settings)
    second = ingest.run(settings)

    assert first == {"loaded": 2, "skipped": 0, "rejected": 0}
    assert second == {"loaded": 0, "skipped": 2, "rejected": 0}
    with pg_connect(settings) as conn:
        (rows,) = conn.execute("SELECT count(*) FROM raw.recordings").fetchone()
    assert rows == 2
    assert len(object_keys(settings, "raw/")) == 2


def test_ingest_rejects_changed_content(settings):
    ingest.run(settings)
    write_tone(settings.ingest_source_dir / FILE_NAMES[0], frequency_hz=440)

    counts = ingest.run(settings)

    assert counts == {"loaded": 0, "skipped": 1, "rejected": 1}


def test_ingest_rejects_damaged_audio_without_stopping(settings):
    (settings.ingest_source_dir / "T03_20230422_014500.ogg").write_bytes(b"not audio")

    counts = ingest.run(settings)

    assert counts == {"loaded": 2, "skipped": 0, "rejected": 1}
    assert len(object_keys(settings, "raw/")) == 2  # nothing uploaded for it


def test_features_write_partitioned_parquet_and_are_idempotent(settings):
    ingest.run(settings)

    results = features.run(settings)
    first = object_keys(settings, "features")
    features.run(settings)

    assert [result.status for _, result in results] == ["ok", "ok"]
    assert first == [
        "features/site=T01/month=2023-04/features.parquet",
        "features/site=T02/month=2023-05/features.parquet",
        "features_failed/failed.parquet",
    ]
    assert object_keys(settings, "features") == first  # re-run adds nothing

    body = s3_client(settings).get_object(Bucket=TEST_BUCKET, Key=first[0])["Body"]
    table = pq.read_table(io.BytesIO(body.read()))
    assert table.schema == features.FEATURES_SCHEMA
    assert table.column("spectral_centroid_hz")[0].as_py() == pytest.approx(
        1000, rel=0.05
    )


def feature_rows(settings: Settings) -> dict[str, float]:
    with pg_connect(settings) as conn:
        rows = conn.execute(
            "SELECT file_name, spectral_centroid_hz FROM raw.audio_features"
        ).fetchall()
    return dict(rows)


def put_table(settings: Settings, key: str, table) -> None:
    features.put_parquet(s3_client(settings), settings.s3_bucket, key, table)


def test_load_is_idempotent_and_updates_re_extracted_features(settings):
    ingest.run(settings)
    features.run(settings)

    first = load.run(settings)
    second = load.run(settings)
    # Other settings force a re-extraction, with a newer extracted_at
    features.run(settings.model_copy(update={"features_n_mfcc": 13}))
    third = load.run(settings)

    assert first == {"read": 2, "inserted": 2, "updated": 0, "unchanged": 0}
    assert second == {"read": 2, "inserted": 0, "updated": 0, "unchanged": 2}
    assert third == {"read": 2, "inserted": 0, "updated": 2, "unchanged": 0}
    assert len(feature_rows(settings)) == 2


def test_load_never_overwrites_with_an_older_extraction(settings):
    ingest.run(settings)
    results = features.run(settings)
    load.run(settings)
    before = feature_rows(settings)

    # Same recordings, different values, but extracted long ago
    recording, result = results[0]
    result.features["spectral_centroid_hz"] = 1.0
    old = datetime(2000, 1, 1, tzinfo=UTC)
    tables, _ = features.build_tables([(recording, result)], 32000, 20, old)
    for key, table in tables.items():
        put_table(settings, key, table)

    counts = load.run(settings)

    assert counts["updated"] == 0
    assert feature_rows(settings) == before


def test_load_is_atomic_and_rejects_features_of_unknown_recordings(settings):
    ingest.run(settings)
    results = features.run(settings)

    # Features for a recording that raw.recordings does not know
    recording, result = results[0]
    orphan = {**recording, "sha256": "f" * 64, "site_code": "T99"}
    tables, _ = features.build_tables([(orphan, result)], 32000, 20, datetime.now(UTC))
    for key, table in tables.items():
        put_table(settings, key, table)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        load.run(settings)
    assert feature_rows(settings) == {}  # the valid rows were not loaded either


def test_features_do_nothing_when_up_to_date(settings):
    ingest.run(settings)
    features.run(settings)
    load.run(settings)

    assert features.run(settings) == []
    assert load.run(settings) == {
        "read": 2,
        "inserted": 0,
        "updated": 0,
        "unchanged": 2,
    }


def test_features_redo_everything_when_settings_or_code_change(settings, monkeypatch):
    ingest.run(settings)
    features.run(settings)

    changed = settings.model_copy(update={"features_n_mfcc": 13})
    assert len(features.run(changed)) == 2

    monkeypatch.setattr(features, "FEATURES_VERSION", features.FEATURES_VERSION + 1)
    assert len(features.run(changed)) == 2


def test_features_new_recording_keeps_the_rows_of_its_partition(settings):
    ingest.run(settings)
    features.run(settings)

    # Same site and month as the first file
    write_tone(settings.ingest_source_dir / "T01_20230423_060000.ogg", 2000)
    ingest.run(settings)
    results = features.run(settings)

    assert len(results) == 1
    key = "features/site=T01/month=2023-04/features.parquet"
    body = s3_client(settings).get_object(Bucket=TEST_BUCKET, Key=key)["Body"]
    assert pq.read_table(io.BytesIO(body.read())).num_rows == 2
