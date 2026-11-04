# Soundscape Data Pipeline

Data pipeline that processes field recordings from El Silencio Nature Reserve (Colombia).

> Work in progress. Data source and decisions: [docs/data_source.md](docs/data_source.md)

## Architecture

```mermaid
flowchart LR
    subgraph sources["Sources"]
        kaggle["BirdCLEF+ 2025<br/>Kaggle"]
        xenocanto["Xeno-canto API"]:::planned
    end

    subgraph s3["Object storage: S3 API (RustFS locally, AWS S3 later)"]
        raw[("raw/<br/>audio .ogg")]
        parquet[("features/<br/>Parquet")]
    end

    subgraph pg["PostgreSQL"]
        recordings[("raw.recordings")]
        audiofeatures[("raw.audio_features")]
        staging[("staging")]:::planned
        marts[("marts")]:::planned
    end

    ingest["ingest<br/>Python"]
    features["features<br/>librosa"]
    load["load<br/>upsert"]
    dbt["dbt"]:::planned
    dashboard["Dashboard"]:::planned
    airflow{{"Apache Airflow"}}

    kaggle --> ingest
    xenocanto -.-> ingest
    ingest --> raw
    ingest --> recordings
    raw --> features --> parquet
    recordings --> features
    parquet --> load --> audiofeatures
    recordings & audiofeatures -.-> dbt
    dbt -.-> staging -.-> marts -.-> dashboard
    airflow -- orchestrates --> ingest & features & load
    airflow -.-> dbt

    classDef planned stroke-dasharray: 5 5, color:#888, stroke:#888
```

Solid lines and boxes are built; dashed ones are planned.

| Stage | Status | What it does |
|---|---|---|
| Ingest | ✅ Built | Uploads raw audio to S3 and registers its metadata in Postgres (idempotent by SHA-256) |
| Features | ✅ Built | Extracts audio features with librosa and writes Parquet partitioned by site and month |
| Load | ✅ Built | Upserts features from Parquet into `raw.audio_features` in Postgres |
| dbt | Planned (E4) | Staging and mart models with data quality tests |
| Dashboard | Planned (E4) | Soundscape by site and period |
| Airflow | ✅ Built | Runs ingest → features → load daily, with retries; re-running a date duplicates nothing |

## How to run

### 1. Prerequisites
- [Docker](https://docs.docker.com/get-docker/) with Docker Compose
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- A Kaggle API token ([how to get one](https://www.kaggle.com/docs/api)) saved in
  `~/.kaggle/access_token`, and the
  [competition rules](https://www.kaggle.com/competitions/birdclef-2025/rules) accepted

### 2. Install dependencies
```bash
uv sync
uv run pre-commit install   # enable the git hooks (once)
```

### 3. Download the data
```bash
uv run bash scripts/download_metadata.sh
uv run bash scripts/list_files.sh
uv run bash scripts/download_sample.sh   # 16 recordings (~8 MB) for local development
```

### 4. Start the services
```bash
cp .env.example .env    # then replace the placeholder secrets (see comments inside)
docker compose build    # build the Airflow image (first time, ~1 min)
docker compose up -d    # start PostgreSQL, RustFS and Airflow
docker compose ps       # every service should be "healthy"
```

| Service | URL | Purpose |
|---|---|---|
| PostgreSQL 18 | `localhost:5432` | Recording metadata and audio features |
| RustFS (S3 API) | `http://localhost:9000` | Raw audio files (S3-compatible object storage) |
| RustFS console | http://localhost:9001/rustfs/console/ | Browse buckets in the browser |
| Airflow 3.3 | http://localhost:8080 | Orchestration UI; user `admin`, password `AIRFLOW_ADMIN_PASSWORD` from `.env` |

On the first `up`, two one-shot services prepare Airflow and then exit:
`airflow-db-init` creates its metadata database inside PostgreSQL and
`airflow-init` migrates it and creates the `admin` user. Airflow reads DAGs
from [`dags/`](dags/); `smoke_check` is a manual DAG that checks tasks can
import the `soundscape` package. Code changes in `src/` apply without
rebuilding; run `docker compose build` again only when dependencies change.

Stop the services with `docker compose down`; data is kept in Docker volumes.
Why RustFS instead of MinIO: [ADR 0001](docs/adr/0001-s3-compatible-storage.md).

### 5. Run the ingestion
```bash
uv run python -m soundscape.ingest   # upload recordings to S3 and register them in Postgres
```
The ingestion is idempotent: re-running it skips recordings already registered
(by SHA-256). Files land in `s3://soundscape/raw/<source>/site=<site>/date=<date>/`
and their metadata in the `raw.recordings` table.

### 6. Extract audio features
```bash
uv run python -m soundscape.features   # write features to S3 as Parquet
```
One row per recording (MFCC, spectral centroid and bandwidth, RMS,
zero-crossing rate), partitioned in `s3://soundscape/features/site=<site>/month=<YYYY-MM>/`.
Recordings that cannot be decoded go to `features_failed/`.
Columns, types and units: [docs/features_schema.md](docs/features_schema.md).

### 7. Load features into Postgres
```bash
uv run python -m soundscape.load   # upsert the Parquet files into raw.audio_features
```
One transaction per run: new recordings are inserted, re-extracted ones
(newer `extracted_at`) are updated, the rest are left unchanged; the log
reports each count. Features of a recording missing from `raw.recordings`
are rejected by a foreign key, and then nothing is loaded.

### 8. Or let Airflow run the whole pipeline
Steps 5–7 are what the `soundscape_pipeline` DAG runs every day, in order,
retrying each task twice. In http://localhost:8080 turn the DAG on (or use
*Trigger*), then open a run to see each task's state and logs; the `load`
log reports the inserted, updated and unchanged counts. *Clear* re-runs a
date safely: every stage is idempotent.

### 9. Verify
```bash
docker compose exec postgres psql -U soundscape -d soundscape \
  -c "SELECT site_code, recorded_at, duration_s FROM raw.recordings ORDER BY recorded_at LIMIT 5;"
uv run pytest                        # all tests, with a coverage report
uv run pytest -m "not integration"   # only the fast tests (no services needed)
uv run --group airflow pytest tests/test_dags.py   # DAGs load (installs Airflow)
```

## License
The code is released under the [MIT](LICENSE) license.

The data is **not** part of this repository nor covered by that license: the BirdCLEF+ 2025 dataset keeps its own [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) license (non-commercial use, with attribution). The pipeline downloads it directly from Kaggle.
