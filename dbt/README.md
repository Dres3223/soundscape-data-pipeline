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
| `dawn` | 05:00–07:59 | Around sunrise |
| `day` | 08:00–16:59 | |
| `dusk` | 17:00–18:59 | Around sunset |
| `night` | 19:00–04:59 | |

These periods are a working choice, not a result: they have not been checked
against the data. Hours assume the file names use Colombian local time (UTC-5),
which is also unverified. Levels (dBFS) are not calibrated, so compare them
within a site, not between sites. Nothing here identifies species or sources.

## Usage

Credentials come from the same `.env` as the pipeline (see `profiles.yml`):

```bash
uv run --env-file .env --group dbt dbt build --project-dir dbt --profiles-dir dbt
```

`dbt build` loads the seed, builds every model in dependency order and runs
the tests; a failing test skips everything downstream of it. Browse the
models, columns and lineage with
`dbt docs generate` and `dbt docs serve --port 8081` (same prefix as above).
Descriptions are also written to Postgres as comments (`persist_docs`).

## Tests

| Where | What is checked |
|---|---|
| Sources | `sha256` unique and not null; every feature row belongs to a recording |
| Seed | Each hour 0–23 exactly once (`assert_day_periods_cover_every_hour`), valid periods |
| Staging | Unique ids, valid periods, dBFS ≤ 0, centroid within 0–16 kHz, and `stg_audio_features` has as many rows as its source (the join with the periods drops none) |
| Mart | One row per site and period, ranks 1–4, at least one recording, variability not null when there are several recordings |

Generic tests from dbt and [dbt_utils](https://hub.getdbt.com/dbt-labs/dbt_utils/latest/)
(`dbt deps` installs it).
