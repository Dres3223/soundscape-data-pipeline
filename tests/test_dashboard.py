"""The dashboard runs end to end on small fake marts (no database).

Needs the dashboard group: uv run --group dashboard pytest tests/test_dashboard.py
"""

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
PERIODS = ["dawn", "day", "dusk", "night"]


def soundscape_mart() -> pd.DataFrame:
    rows = []
    for site, offset in [("H01", 0.0), ("H02", 3.0)]:
        for order, period in enumerate(PERIODS, start=1):
            rows.append(
                {
                    "site_code": site,
                    "period": period,
                    "period_order": order,
                    "n_recordings": 20,
                    "n_excluded": 1,
                    "avg_rms_dbfs": -40.0 + offset + order,
                    "stddev_rms_dbfs": 2.0,
                    "avg_spectral_centroid_hz": 5000.0 + 100 * order,
                    "avg_spectral_bandwidth_hz": 3000.0,
                    "avg_zero_crossing_rate": 0.3,
                    "avg_aci": 300.0,
                    "avg_adi": 2.2,
                    "avg_aei": 0.1,
                    "avg_bi": 50.0 + order,
                    "avg_ndsi": 0.5,
                    "avg_ht": 0.9,
                    "avg_hf": 0.8,
                    "avg_snrt_db": 1.0,
                    "rms_dbfs_vs_site_avg": order - 2.5,
                    "loudness_rank_in_site": 5 - order,
                    "rms_dbfs_change_vs_previous": None if order == 1 else 1.0,
                    "centroid_hz_change_vs_previous": None,
                }
            )
    return pd.DataFrame(rows)


def species_mart() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["H01", "dawn", 1, "Crypturellus soui", "Little Tinamou", 5, 20, 0.25, 0.9],
            ["H02", "dusk", 3, "Crypturellus soui", "Little Tinamou", 2, 20, 0.1, 0.7],
            [
                "H02",
                "dawn",
                1,
                "Patagioenas cayennensis",
                "Pale-vented Pigeon",
                3,
                20,
                0.15,
                0.8,
            ],
        ],
        columns=[
            "site_code",
            "period",
            "period_order",
            "scientific_name",
            "common_name",
            "n_recordings_detected",
            "n_recordings_analyzed",
            "detection_rate",
            "max_confidence",
        ],
    )


def fake_connect(**_):
    """A psycopg connection whose queries return the fake marts."""
    marts = {"mart_soundscape": soundscape_mart(), "mart_species": species_mart()}

    def execute(query):
        frame = next(df for key, df in marts.items() if key in query)
        return SimpleNamespace(
            description=[SimpleNamespace(name=c) for c in frame.columns],
            fetchall=lambda: list(frame.itertuples(index=False, name=None)),
        )

    conn = mock.MagicMock()
    conn.__enter__.return_value.execute = execute
    return conn


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_DB_PASSWORD", "test")
    with mock.patch("psycopg.connect", fake_connect):
        test = AppTest.from_file(str(APP), default_timeout=60)
        test.run()
        yield test


def test_dashboard_runs_and_shows_both_tabs(app):
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Soundscape", "Birds (BirdNET)"]
    assert app.sidebar.metric[0].value == "2"  # sites shown
    assert app.sidebar.metric[1].value == "160"  # 2 sites x 4 periods x 20


def test_every_measure_and_species_can_be_shown(app):
    measure, site, species = app.selectbox
    for label in measure.options:
        measure.select(label).run()
        assert not app.exception, label
    site.select("H02").run()
    species.select("Patagioenas cayennensis").run()
    assert not app.exception
    assert app.tabs[1].metric[0].value == "2"  # species detected


def test_a_minimum_above_every_group_says_so(app):
    app.sidebar.slider[0].set_value(50).run()

    assert not app.exception
    assert "lower the minimum" in app.warning[0].value
