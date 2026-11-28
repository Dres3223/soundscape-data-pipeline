"""Soundscape dashboard: El Silencio by site and period of the day.

Reads two dbt marts with a read-only Postgres role:
    marts.mart_soundscape_by_point_period  acoustic measures, usable recordings
    marts.mart_species_by_site_period      BirdNET detections that pass both flags
Run with Docker Compose (http://localhost:8501) or locally:
    DASHBOARD_DB_PASSWORD=... uv run --group dashboard streamlit run dashboard/app.py
"""

import os

import altair as alt
import pandas as pd
import psycopg
import streamlit as st

PERIODS = ["dawn", "day", "dusk", "night"]  # in order through the day
SOUNDSCAPE = "SELECT * FROM marts.mart_soundscape_by_point_period"
SPECIES = "SELECT * FROM marts.mart_species_by_site_period"

# Measure shown in the map: column, and whether its colours centre on zero
MEASURES = {
    "Level vs the site's average (dB)": ("rms_dbfs_vs_site_avg", True),
    "Bioacoustic Index (BI)": ("avg_bi", False),
    "NDSI: 2–8 kHz against 1–2 kHz": ("avg_ndsi", True),
    "Acoustic Complexity Index (ACI)": ("avg_aci", False),
    "Acoustic Diversity Index (ADI)": ("avg_adi", False),
    "Acoustic Evenness Index (AEI)": ("avg_aei", False),
    "Temporal entropy (Ht)": ("avg_ht", False),
    "Spectral entropy (Hf)": ("avg_hf", False),
    "Spectral centroid (Hz)": ("avg_spectral_centroid_hz", False),
    "Signal-to-noise ratio (dB)": ("avg_snrt_db", False),
}


@st.cache_data(ttl=600)  # the marts only change when dbt runs
def load(query: str) -> pd.DataFrame:
    with psycopg.connect(
        host=os.environ.get("DASHBOARD_DB_HOST", "localhost"),
        port=int(os.environ.get("DASHBOARD_DB_PORT", "5432")),
        dbname=os.environ.get("DASHBOARD_DB_NAME", "soundscape"),
        user=os.environ.get("DASHBOARD_DB_USER", "dashboard"),
        password=os.environ["DASHBOARD_DB_PASSWORD"],
    ) as conn:
        cursor = conn.execute(query)
        columns = [column.name for column in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=columns)


def species_grid(soundscape: pd.DataFrame, species: pd.DataFrame, name: str):
    """Detection rate of one species in every site and period shown, 0 where
    the usable recordings had no detection of it (the mart has no such rows)."""
    found = species.loc[
        species["scientific_name"] == name,
        ["site_code", "period", "n_recordings_detected", "max_confidence"],
    ]
    grid = soundscape[["site_code", "period", "n_recordings", "enough"]].merge(
        found, on=["site_code", "period"], how="left"
    )
    grid["n_recordings_detected"] = grid["n_recordings_detected"].fillna(0)
    grid["detection_rate"] = grid["n_recordings_detected"] / grid["n_recordings"]
    return grid


def site_map(data: pd.DataFrame, color: alt.Color, tooltip: list, n_sites: int):
    """Sites down, periods across: 56 sites stay readable at 16 px a row.
    Groups with fewer recordings than the minimum (enough = False) are grey,
    never left blank: a blank cell would look like a value."""
    return (
        alt.Chart(data)
        .mark_rect()
        .encode(
            alt.X(
                "period:N",
                sort=PERIODS,
                title="Period of the day",
                axis=alt.Axis(labelAngle=0, orient="top"),
            ),
            # labelOverlap=False: show every site name, never hide one
            alt.Y("site_code:N", title="Site", axis=alt.Axis(labelOverlap=False)),
            color=alt.condition("datum.enough", color, alt.value("#8a8a8a")),
            tooltip=tooltip,
        )
        .properties(height=max(160, 16 * n_sites))
    )


st.set_page_config(page_title="El Silencio soundscape", layout="wide")
st.title("El Silencio soundscape")
st.caption(
    "One-minute field recordings from El Silencio Nature Reserve (Colombia), "
    "April–May 2023, summarised by site and period of the day (assumed local "
    "time, UTC-5). Only recordings without a quality flag. Data: BirdCLEF+ 2025."
)

try:
    soundscape = load(SOUNDSCAPE)
    species = load(SPECIES)
except (psycopg.Error, KeyError) as error:
    st.error(f"Cannot read the marts. Did `dbt build` run? ({type(error).__name__})")
    st.stop()

min_recordings = st.sidebar.slider(
    "Minimum recordings per site and period",
    min_value=1,
    max_value=50,
    value=10,
    help="Groups with few recordings are not representative.",
)
soundscape["enough"] = soundscape["n_recordings"] >= min_recordings
data = soundscape[soundscape["enough"]]
if data.empty:
    st.warning("No site has that many recordings per period; lower the minimum.")
    st.stop()
sites = sorted(data["site_code"].unique())
# Every period of the sites shown, so the maps have no blank cells
grid = soundscape[soundscape["site_code"].isin(sites)]
GREY_NOTE = "Grey: fewer recordings than the minimum in the sidebar."
st.sidebar.metric("Sites shown", len(sites))
st.sidebar.metric("Recordings", f"{int(data['n_recordings'].sum()):,}")

sound_tab, birds_tab = st.tabs(["Soundscape", "Birds (BirdNET)"])

with sound_tab:
    st.info(
        "Acoustic measures do not say which species or source made the sound. "
        "Recorders are not calibrated: compare periods within a site, not sites "
        "with each other. The indices are context, not measures of biodiversity."
    )
    label = st.selectbox("Measure", list(MEASURES))
    column, centred = MEASURES[label]
    scale = (
        alt.Scale(scheme="redblue", reverse=True, domainMid=0)
        if centred
        else alt.Scale(scheme="viridis")
    )
    st.subheader(f"{label}, by site and period")
    st.caption(GREY_NOTE)
    st.altair_chart(
        site_map(
            grid,
            alt.Color(f"{column}:Q", title=None, scale=scale),
            [
                "site_code",
                "period",
                alt.Tooltip("n_recordings:Q", title="recordings"),
                alt.Tooltip(f"{column}:Q", format=",.2f", title=label),
            ],
            len(sites),
        ),
        width="stretch",
    )

    st.subheader("One site through the day")
    site = st.selectbox("Site", sites)
    profile = data[data["site_code"] == site].assign(
        low=lambda df: df["avg_rms_dbfs"] - df["stddev_rms_dbfs"].fillna(0),
        high=lambda df: df["avg_rms_dbfs"] + df["stddev_rms_dbfs"].fillna(0),
    )
    left, right = st.columns(2)
    with left:
        base = alt.Chart(profile).encode(
            alt.X("period:N", sort=PERIODS, title=None, axis=alt.Axis(labelAngle=0))
        )
        st.altair_chart(
            base.mark_errorbar().encode(
                alt.Y(
                    "low:Q",
                    title="Level (dBFS, ± 1 std)",
                    scale=alt.Scale(zero=False),  # 0 dBFS would squash the points
                ),
                alt.Y2("high:Q"),
            )
            + base.mark_point(filled=True, size=90).encode(alt.Y("avg_rms_dbfs:Q")),
            width="stretch",
        )
    with right:
        # Columns computed with window functions in dbt
        st.dataframe(
            profile.sort_values("period_order")[
                [
                    "period",
                    "n_recordings",
                    "n_excluded",
                    "avg_rms_dbfs",
                    "rms_dbfs_vs_site_avg",
                    "loudness_rank_in_site",
                    "rms_dbfs_change_vs_previous",
                ]
            ].rename(
                columns={
                    "n_recordings": "recordings",
                    "n_excluded": "excluded",
                    "avg_rms_dbfs": "avg dBFS",
                    "rms_dbfs_vs_site_avg": "vs site avg (dB)",
                    "loudness_rank_in_site": "rank",
                    "rms_dbfs_change_vs_previous": "Δ previous (dB)",
                }
            ),
            hide_index=True,
            column_config={
                name: st.column_config.NumberColumn(format="%.1f")
                for name in ["avg dBFS", "vs site avg (dB)", "Δ previous (dB)"]
            },
        )
        st.caption(
            "Excluded: recordings left out for heavy rain, low-frequency noise, "
            "clipping or dropouts. Dawn has no previous period."
        )

with birds_tab:
    st.warning(
        "**Automatic detections, not observations.** Checked against published "
        "labels from the reserve, about 8 in 10 species BirdNET reports in a "
        "recording are right, but only about 1 in 7 species present is found. "
        "A species missing here may well have been there, and the rates "
        "undercount how often a species calls."
    )
    # Only groups with enough recordings, as in the soundscape tab
    shown = species.merge(data[["site_code", "period"]], on=["site_code", "period"])
    if shown.empty:
        st.info("No detection passes the thresholds in the sites shown.")
        st.stop()
    widespread = (
        shown.groupby(["scientific_name", "common_name"], as_index=False)
        .agg(
            sites=("site_code", "nunique"),
            recordings=("n_recordings_detected", "sum"),
        )
        .sort_values(["sites", "recordings"], ascending=False)
    )
    st.metric("Species detected in the sites shown", len(widespread))

    st.subheader("Most widespread species")
    st.altair_chart(
        alt.Chart(widespread.head(20))
        .mark_bar()
        .encode(
            alt.X("sites:Q", title="Sites where BirdNET detected it"),
            alt.Y(
                "common_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)
            ),
            tooltip=["common_name", "scientific_name", "sites", "recordings"],
        ),
        width="stretch",
    )

    st.subheader("Where and when one species was detected")
    labels = dict(
        zip(
            widespread["scientific_name"],
            widespread["common_name"] + " (" + widespread["scientific_name"] + ")",
            strict=True,
        )
    )
    name = st.selectbox("Species", list(labels), format_func=labels.get)
    st.caption(
        "Share of each site's usable recordings in that period with at least "
        f"one detection. {GREY_NOTE}"
    )
    st.altair_chart(
        site_map(
            species_grid(grid, shown, name),
            alt.Color(
                "detection_rate:Q",
                title="Detection rate",
                # Dark for 0, so "never detected" stands out from rare
                scale=alt.Scale(scheme="viridis", domainMin=0),
            ),
            [
                "site_code",
                "period",
                alt.Tooltip("n_recordings_detected:Q", title="recordings with it"),
                alt.Tooltip("n_recordings:Q", title="recordings"),
                alt.Tooltip("detection_rate:Q", format=".0%", title="rate"),
                alt.Tooltip("max_confidence:Q", format=".2f", title="best score"),
            ],
            len(sites),
        ),
        width="stretch",
    )
