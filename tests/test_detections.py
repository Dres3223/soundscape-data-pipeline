import sys
import types
from datetime import UTC, datetime

import pandas as pd
import pyarrow as pa

from soundscape import detections
from soundscape.detections import (
    DETECTIONS_SCHEMA,
    DETECTIONS_VERSION,
    MODEL_VERSION,
    RECORDINGS_SCHEMA,
    birdnet_week,
    build_tables,
    is_up_to_date,
    split_species,
)

DETECTED_AT = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
SEED_FINCH = "Sporophila funerea_Thick-billed Seed-Finch"


def recording(site: str, recorded_at: datetime) -> dict:
    return {
        "sha256": f"{site}{recorded_at:%Y%m%d%H%M}".ljust(64, "0"),
        "file_name": f"{site}_{recorded_at:%Y%m%d_%H%M%S}.ogg",
        "site_code": site,
        "recorded_at": recorded_at,
        "s3_key": "raw/x.ogg",
    }


def found_in(file_name: str, *labels: str) -> dict[str, list[dict]]:
    return {
        file_name: [
            {
                "start_s": 3.0 * i,
                "end_s": 3.0 * i + 3,
                "label": label,
                "confidence": 0.8,
            }
            for i, label in enumerate(labels)
        ]
    }


def test_birdnet_week_has_four_weeks_per_month():
    assert birdnet_week(datetime(2023, 1, 1)) == 1
    assert birdnet_week(datetime(2023, 4, 19)) == 15
    assert birdnet_week(datetime(2023, 4, 30)) == 16  # days 22-31 are week 4
    assert birdnet_week(datetime(2023, 5, 26)) == 20
    assert birdnet_week(datetime(2023, 12, 31)) == 48


def test_split_species_keeps_scientific_and_common_name():
    assert split_species(SEED_FINCH) == (
        "Sporophila funerea",
        "Thick-billed Seed-Finch",
    )
    assert split_species("Engine_Engine") == ("Engine", "Engine")


def test_is_up_to_date_needs_success_same_model_and_version():
    row = {
        "status": "ok",
        "model_version": MODEL_VERSION,
        "detections_version": DETECTIONS_VERSION,
    }

    assert is_up_to_date(row)
    assert not is_up_to_date(None)
    assert not is_up_to_date({**row, "status": "failed"})
    assert not is_up_to_date({**row, "model_version": "3.0"})
    assert not is_up_to_date({**row, "detections_version": 0})


def test_build_tables_lists_every_recording_even_without_detections():
    with_birds = recording("H02", datetime(2023, 4, 20, 6, 0))
    silent = recording("H02", datetime(2023, 4, 21, 6, 0))
    broken = recording("H02", datetime(2023, 4, 22, 6, 0))
    geo = {birdnet_week(with_birds["recorded_at"]): {SEED_FINCH: 0.09}}

    tables = build_tables(
        [with_birds, silent, broken],
        found_in(with_birds["file_name"], SEED_FINCH, "Engine_Engine"),
        {broken["file_name"]: "BirdNET could not read the audio"},
        geo,
        DETECTED_AT,
    )

    prefix = "detections/site=H02/month=2023-04/"
    assert sorted(tables) == [
        prefix + "detections.parquet",
        prefix + "recordings.parquet",
    ]
    analyzed = tables[prefix + "recordings.parquet"].to_pylist()
    assert [(r["status"], r["n_detections"]) for r in analyzed] == [
        ("ok", 2),
        ("ok", 0),
        ("failed", 0),
    ]
    rows = tables[prefix + "detections.parquet"].to_pylist()
    assert [(r["scientific_name"], r["geo_score"]) for r in rows] == [
        ("Sporophila funerea", 0.09000000357627869),  # float32
        ("Engine", None),  # unknown to the geographic model
    ]
    assert tables[prefix + "detections.parquet"].schema == DETECTIONS_SCHEMA
    assert tables[prefix + "recordings.parquet"].schema == RECORDINGS_SCHEMA


def test_kept_rows_only_fill_partitions_with_new_results():
    new = recording("H02", datetime(2023, 4, 20, 6, 0))
    april, may = (
        "detections/site=H02/month=2023-04/",
        "detections/site=H02/month=2023-05/",
    )
    old = build_tables(
        [
            recording("H02", datetime(2023, 4, 1)),
            recording("H02", datetime(2023, 5, 1)),
        ],
        {},
        {},
        {},
        DETECTED_AT,
    )
    kept = {
        prefix: (old[prefix + "recordings.parquet"].to_pylist(), [])
        for prefix in (april, may)
    }

    tables = build_tables([new], {}, {}, {}, DETECTED_AT, kept)

    assert sorted(tables) == [
        april + "detections.parquet",
        april + "recordings.parquet",
    ]
    assert tables[april + "recordings.parquet"].num_rows == 2


def test_empty_tables_keep_their_schema():
    tables = build_tables(
        [recording("H02", datetime(2023, 4, 1))], {}, {}, {}, DETECTED_AT
    )

    table = tables["detections/site=H02/month=2023-04/detections.parquet"]
    assert table.num_rows == 0
    assert isinstance(table, pa.Table)
    assert detections.PREFIX == "detections/"


class FakeResult:
    """What BirdNET's predict returns: inputs sorted, failures as indices."""

    def __init__(self, paths, unreadable):
        self.inputs = sorted({str(path) for path in paths})
        self.unprocessable_inputs = [
            index for index, path in enumerate(self.inputs) if path in unreadable
        ]
        self.rows = [
            (path, 0.0, 3.0, SEED_FINCH, 0.9)
            for path in self.inputs
            if path not in unreadable
        ]

    def to_dataframe(self):
        columns = ["input", "start_time", "end_time", "species_name", "confidence"]
        return pd.DataFrame(self.rows, columns=columns)


def test_detect_names_the_files_birdnet_could_not_read(monkeypatch, tmp_path):
    good, bad = tmp_path / "b_good.ogg", tmp_path / "a_bad.ogg"

    class Model:
        def predict(self, paths, **kwargs):
            return FakeResult(paths, {str(bad)})

    fake = types.SimpleNamespace(load=lambda *args, **kwargs: Model())
    monkeypatch.setitem(sys.modules, "birdnet", fake)

    # `bad` is second in the list but first once BirdNET sorts the inputs
    found, failed = detections.detect([good, bad])

    assert failed == {"a_bad.ogg": "BirdNET could not read the audio"}
    assert list(found) == ["b_good.ogg"]
