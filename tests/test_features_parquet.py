import io
from datetime import UTC, datetime

import pyarrow.parquet as pq

from soundscape.features import (
    FAILED_SCHEMA,
    FEATURES_SCHEMA,
    FEATURES_VERSION,
    FeatureResult,
    build_tables,
    is_up_to_date,
    partition_key,
)

EXTRACTED_AT = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def recording(site: str, recorded_at: datetime) -> dict:
    file_name = f"{site}_{recorded_at:%Y%m%d_%H%M%S}.ogg"
    return {
        "sha256": "0" * 64,
        "file_name": file_name,
        "site_code": site,
        "recorded_at": recorded_at,
        "s3_key": f"raw/test/{file_name}",
    }


def ok(n_mfcc: int = 20) -> FeatureResult:
    return FeatureResult(
        "ok",
        {
            "duration_s": 60.0,
            "mfcc_mean": [1.0] * n_mfcc,
            "mfcc_std": [0.5] * n_mfcc,
            "spectral_centroid_hz": 6000.0,
            "spectral_bandwidth_hz": 4000.0,
            "rms_mean": 0.01,
            "zcr_mean": 0.2,
        },
    )


def test_partition_key_is_site_and_month():
    key = partition_key("H02", datetime(2023, 4, 22, 1, 45))
    assert key == "features/site=H02/month=2023-04/features.parquet"


def test_build_tables_groups_by_partition_and_keeps_failures_apart():
    results = [
        (recording("H02", datetime(2023, 4, 1)), ok()),
        (recording("H02", datetime(2023, 4, 30)), ok()),
        (recording("H02", datetime(2023, 5, 1)), ok()),
        (
            recording("O201", datetime(2023, 4, 1)),
            FeatureResult("failed", error="audio has no samples"),
        ),
    ]

    tables, failed = build_tables(results, 32000, 20, EXTRACTED_AT)

    rows_per_partition = {key: table.num_rows for key, table in tables.items()}
    assert rows_per_partition == {
        "features/site=H02/month=2023-04/features.parquet": 2,
        "features/site=H02/month=2023-05/features.parquet": 1,
    }
    assert failed.column("error").to_pylist() == ["audio has no samples"]


def test_schema_is_fixed_whatever_n_mfcc():
    for n_mfcc in (13, 20):
        results = [(recording("H02", datetime(2023, 4, 1)), ok(n_mfcc))]
        tables, failed = build_tables(results, 32000, n_mfcc, EXTRACTED_AT)
        (table,) = tables.values()

        assert table.schema == FEATURES_SCHEMA
        assert failed.schema == FAILED_SCHEMA
        assert len(table.column("mfcc_mean")[0]) == n_mfcc


def test_tables_round_trip_through_parquet():
    results = [(recording("H02", datetime(2023, 4, 1, 6, 30)), ok())]
    tables, _ = build_tables(results, 32000, 20, EXTRACTED_AT)
    (table,) = tables.values()

    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    buffer.seek(0)
    row = pq.read_table(buffer).to_pylist()[0]

    assert row["recorded_at"] == datetime(2023, 4, 1, 6, 30)
    assert row["sample_rate_hz"] == 32000
    assert row["n_mfcc"] == 20
    assert row["extracted_at"] == EXTRACTED_AT


def stored_row(site: str, recorded_at: datetime) -> dict:
    results = [(recording(site, recorded_at), ok())]
    tables, _ = build_tables(results, 32000, 20, EXTRACTED_AT)
    (table,) = tables.values()
    return table.to_pylist()[0]


def test_is_up_to_date_compares_settings_and_version():
    row = {"sample_rate_hz": 32000, "n_mfcc": 20, "features_version": FEATURES_VERSION}

    assert is_up_to_date(row, 32000, 20)
    assert not is_up_to_date(None, 32000, 20)
    assert not is_up_to_date(row, 16000, 20)
    assert not is_up_to_date(row, 32000, 13)
    assert not is_up_to_date({**row, "features_version": 0}, 32000, 20)


def test_kept_rows_only_fill_partitions_with_new_results():
    april = stored_row("H02", datetime(2023, 4, 1))
    may = stored_row("H02", datetime(2023, 5, 1))
    new = [(recording("H02", datetime(2023, 4, 2)), ok())]
    later = datetime(2026, 11, 9, tzinfo=UTC)

    tables, _ = build_tables(new, 32000, 20, later, kept_rows=[april, may])

    assert list(tables) == ["features/site=H02/month=2023-04/features.parquet"]
    rows = tables["features/site=H02/month=2023-04/features.parquet"].to_pylist()
    # Sorted by time; the kept row keeps its original extraction date
    assert [row["extracted_at"] for row in rows] == [EXTRACTED_AT, later]
