# dbt

dbt project that turns the raw tables loaded by the pipeline into
analysis-ready models (epic E4). dbt Core v1 with the Postgres adapter.

```
raw.recordings ────────→ staging.stg_recordings
raw.audio_features ──┬─→ staging.stg_audio_features ──→ marts.mart_soundscape_by_point_period
seed day_periods ────┘
```

| Layer | Schema | Materialized | Purpose |
|---|---|---|---|
| sources | `raw` | (pipeline tables) | Written by `soundscape.ingest` and `soundscape.load`; dbt only reads them |
| seed | `staging` | table | `day_periods`: ecological period of each local hour |
| staging | `staging` | view | One row per recording, clean names and types |
| marts | `marts` | table | Aggregates for analysis and the dashboard |

## Periods of the day

El Silencio is at 6.76° N, so sunrise (~05:45) and sunset (~18:00) barely
change during the year and the periods can use fixed local hours
([`seeds/day_periods.csv`](seeds/day_periods.csv)):

| Period | Local hours | Why |
|---|---|---|
| `dawn` | 05:00–07:59 | Dawn chorus: the most active time for birds |
| `day` | 08:00–16:59 | |
| `dusk` | 17:00–18:59 | Dusk chorus |
| `night` | 19:00–04:59 | Insects and amphibians |

## Usage

Credentials come from the same `.env` as the pipeline (see `profiles.yml`):

```bash
uv run --env-file .env --group dbt dbt build --project-dir dbt --profiles-dir dbt
```

`dbt build` loads the seed, builds every model in dependency order and runs
the tests.
