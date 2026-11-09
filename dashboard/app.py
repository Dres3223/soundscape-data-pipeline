"""Soundscape dashboard: El Silencio by site and period of the day.

Reads marts.mart_soundscape_by_point_period (built by dbt) with a read-only
Postgres role. Run with Docker Compose (http://localhost:8501) or locally:
    DASHBOARD_DB_PASSWORD=... uv run --group dashboard streamlit run dashboard/app.py
"""

import os

import altair as alt
import pandas as pd
import psycopg
import streamlit as st

PERIODS = ["dawn", "day", "dusk", "night"]  # in order through the day
QUERY = "SELECT * FROM marts.mart_soundscape_by_point_period"


@st.cache_data(ttl=600)  # the mart only changes when dbt runs
def load_mart() -> pd.DataFrame:
    with psycopg.connect(
        host=os.environ.get("DASHBOARD_DB_HOST", "localhost"),
        port=int(os.environ.get("DASHBOARD_DB_PORT", "5432")),
        dbname=os.environ.get("DASHBOARD_DB_NAME", "soundscape"),
        user=os.environ.get("DASHBOARD_DB_USER", "dashboard"),
        password=os.environ["DASHBOARD_DB_PASSWORD"],
    ) as conn:
        cursor = conn.execute(QUERY)
        columns = [column.name for column in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=columns)


st.set_page_config(page_title="El Silencio soundscape", layout="wide")
st.title("El Silencio soundscape")
st.caption(
    "Field recordings from El Silencio Nature Reserve (Colombia), summarised by "
    "site and period of the day (assumed local time, UTC-5). Data: BirdCLEF+ 2025."
)
st.info(
    "Exploratory view of acoustic measurements. Levels are not calibrated, so "
    "compare them within a site, not between sites. These numbers do not say "
    "which species or source produced the sound."
)

try:
    mart = load_mart()
except (psycopg.Error, KeyError) as error:
    st.error(f"Cannot read the mart. Did `dbt build` run? ({type(error).__name__})")
    st.stop()

min_recordings = st.sidebar.slider(
    "Minimum recordings per site and period",
    min_value=1,
    max_value=50,
    value=10,
    help="Groups with few recordings are not representative.",
)
data = mart[mart["n_recordings"] >= min_recordings]
if data.empty:
    st.warning("No site has that many recordings per period; lower the minimum.")
    st.stop()

sites = sorted(data["site_code"].unique())
st.sidebar.metric("Sites shown", len(sites))
st.sidebar.metric("Recordings", int(data["n_recordings"].sum()))
period_axis = alt.X(
    "period:N", sort=PERIODS, title="Period of the day", axis=alt.Axis(labelAngle=0)
)

# 1. Each period against its own site: absolute levels depend on the recorder
st.subheader("Level of each period relative to its site's average")
st.altair_chart(
    alt.Chart(data)
    .mark_rect()
    .encode(
        period_axis,
        # labelOverlap=False: show every site name, never hide one
        alt.Y("site_code:N", title="Site", axis=alt.Axis(labelOverlap=False)),
        alt.Color(
            "rms_dbfs_vs_site_avg:Q",
            title="dB vs site",
            scale=alt.Scale(scheme="redblue", reverse=True, domainMid=0),
        ),
        tooltip=[
            "site_code",
            "period",
            "n_recordings",
            alt.Tooltip("rms_dbfs_vs_site_avg:Q", format=".1f", title="dB vs site"),
            alt.Tooltip("avg_rms_dbfs:Q", format=".1f", title="avg dBFS"),
            alt.Tooltip("loudness_rank_in_site:Q", title="rank in site"),
        ],
    )
    .properties(height=max(160, 55 * len(sites))),
    use_container_width=True,
)

# 2. One site through the day, with its variability
st.subheader("One site through the day")
site = st.selectbox("Site", sites)
profile = data[data["site_code"] == site].assign(
    low=lambda df: df["avg_rms_dbfs"] - df["stddev_rms_dbfs"].fillna(0),
    high=lambda df: df["avg_rms_dbfs"] + df["stddev_rms_dbfs"].fillna(0),
)
left, right = st.columns(2)
with left:
    base = alt.Chart(profile).encode(period_axis)
    st.altair_chart(
        base.mark_errorbar().encode(
            alt.Y(
                "low:Q",
                title="Loudness (dBFS, ± 1 std)",
                scale=alt.Scale(zero=False),  # 0 dBFS would squash the points
            ),
            alt.Y2("high:Q"),
        )
        + base.mark_point(filled=True, size=90).encode(alt.Y("avg_rms_dbfs:Q")),
        use_container_width=True,
    )
with right:
    # Columns computed with window functions in dbt
    st.dataframe(
        profile.sort_values("period_order")[
            [
                "period",
                "n_recordings",
                "avg_rms_dbfs",
                "rms_dbfs_vs_site_avg",
                "loudness_rank_in_site",
                "rms_dbfs_change_vs_previous",
            ]
        ].rename(
            columns={
                "n_recordings": "recordings",
                "avg_rms_dbfs": "avg dBFS",
                "rms_dbfs_vs_site_avg": "vs site avg (dB)",
                "loudness_rank_in_site": "rank",
                "rms_dbfs_change_vs_previous": "change vs previous (dB)",
            }
        ),
        hide_index=True,
        column_config={
            name: st.column_config.NumberColumn(format="%.1f")
            for name in ["avg dBFS", "vs site avg (dB)", "change vs previous (dB)"]
        },
    )
    st.caption(
        "Window functions in dbt compare each period with its site; "
        "dawn has no previous period."
    )

# 3. How high-pitched the soundscape is at each moment
st.subheader("Spectral centroid by period")
st.caption("Higher centroid = more of the energy at high frequencies.")
st.altair_chart(
    alt.Chart(data)
    .mark_line(point=True)
    .encode(
        period_axis,
        alt.Y("avg_spectral_centroid_hz:Q", title="Hz", scale=alt.Scale(zero=False)),
        alt.Color("site_code:N", title="Site"),
        tooltip=[
            "site_code",
            "period",
            alt.Tooltip("avg_spectral_centroid_hz:Q", format=",.0f"),
        ],
    ),
    use_container_width=True,
)
