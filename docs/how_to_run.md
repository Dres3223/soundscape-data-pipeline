# How to run the pipeline, step by step

What `make setup`, `make data`, `make up`, `make run` and `make release` do,
one command at a time. Back to the [README](../README.md).

## 1. Prerequisites
- [Docker](https://docs.docker.com/get-docker/) with Docker Compose
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- A Kaggle API token ([how to get one](https://www.kaggle.com/docs/api)) saved in
  `~/.kaggle/access_token`, and the
  [competition rules](https://www.kaggle.com/competitions/birdclef-2025/rules) accepted
- `make` (included in macOS and Linux)

## Quick start
```bash
make setup   # dependencies, git hooks, and .env with random secrets
make data    # dataset metadata and the 16-recording sample from Kaggle
make up      # build and start Postgres, RustFS, Airflow and the dashboard
make run     # ingest → features → detections → load → dbt build
```
Then open the dashboard at http://localhost:8501. `make` alone lists every
command (`make test`, `make lint`, `make down`...). The numbered steps below
are what these commands run, one at a time.

## 2. Install dependencies
```bash
uv sync
uv run pre-commit install   # enable the git hooks (once)
```

## 3. Download the data
```bash
uv run bash scripts/download_metadata.sh
uv run bash scripts/list_files.sh
uv run bash scripts/download_sample.sh   # 16 recordings (~8 MB) for local development
# Optional: every recording of some sites (~178 each), so the marts can
# compare periods of the day within a site
uv run bash scripts/download_sample.sh H02 H24 O203 H85   # ~330 MB
# Or all 9,726 recordings (~4.3 GB), in one request (~15 min)
bash scripts/download_all.sh
```
Kaggle limits single-file downloads: after a few hundred it allows about 32
every 30 minutes, so `download_sample.sh` would take days for the full set.
`download_all.sh` streams the whole competition archive (12.4 GB) and keeps
only the soundscapes, without storing the archive.

## 4. Start the services
```bash
bash scripts/make_env.sh   # .env from .env.example, with random secrets
docker compose build    # build the Airflow image (first time, ~1 min)
docker compose up -d    # start PostgreSQL, RustFS, Airflow and the dashboard
docker compose ps       # every service should be "healthy"
```

| Service | URL | Purpose |
|---|---|---|
| PostgreSQL 18 | `localhost:5432` | Recording metadata, audio features, detections and dbt models |
| RustFS (S3 API) | `http://localhost:9000` | Raw audio files (S3-compatible object storage) |
| RustFS console | http://localhost:9001/rustfs/console/ | Browse buckets in the browser |
| Airflow 3.3 | http://localhost:8080 | Orchestration UI; user `admin`, password `AIRFLOW_ADMIN_PASSWORD` from `.env` |
| Dashboard | http://localhost:8501 | Soundscape by site and period (after `dbt build`) |

On the first `up`, two one-shot services prepare Airflow and then exit:
`postgres-init` creates Airflow's metadata database and the dashboard's read-only role, and
`airflow-init` migrates it and creates the `admin` user. Airflow reads DAGs
from [`dags/`](../dags/); `smoke_check` is a manual DAG that checks tasks can
import the `soundscape` package. Code changes in `src/` apply without
rebuilding; run `docker compose build` again only when dependencies change.

Stop the services with `docker compose down`; data is kept in Docker volumes.
Why RustFS instead of MinIO: [ADR 0001](adr/0001-s3-compatible-storage.md).

## 5. Run the ingestion
```bash
uv run python -m soundscape.ingest   # upload recordings to S3 and register them in Postgres
```
The ingestion is idempotent: re-running it skips recordings already registered
(by SHA-256). Files land in `s3://soundscape/raw/<source>/site=<site>/date=<date>/`
and their metadata in the `raw.recordings` table.

## 6. Extract audio features
```bash
uv run python -m soundscape.features   # write features to S3 as Parquet
```
One row per recording, partitioned in
`s3://soundscape/features/site=<site>/month=<YYYY-MM>/`: MFCC, spectral
centroid and bandwidth, RMS and zero-crossing rate (librosa); ecoacoustic
indices (scikit-maad: ACI, ADI, AEI, BI, NDSI, entropies, noise and SNR); and
quality measures (rain band, low-frequency energy, clipping, dropouts).
Recordings are analyzed in parallel (`FEATURES_WORKERS`, default: cores − 2)
and written every 250, so a stopped run carries on where it left off.
Recordings that cannot be decoded go to `features_failed/`.
Columns, types and units: [docs/features_schema.md](features_schema.md).

```bash
uv run python -m soundscape.detections   # bird species with BirdNET, to S3 as Parquet
```
Automatic detections per 3-second segment, in
`s3://soundscape/detections/site=<site>/month=<YYYY-MM>/`; the first run
downloads the BirdNET models (~90 MB). Details and limits:
[docs/detections_schema.md](detections_schema.md). Against the published
labels of El Silencio, about 8 in 10 species detected in a recording are
right and 1 in 7 labeled species is found:
[docs/validation.md](validation.md), reproduced with
`uv run python -m soundscape.validation`.

## 7. Load features and detections into Postgres
```bash
uv run python -m soundscape.load   # upsert the Parquet files into Postgres
```
Features go to `raw.audio_features` in one transaction: new recordings are
inserted, re-extracted ones (newer `extracted_at`) are updated, the rest are
left unchanged; the log reports each count. Detections go to
`raw.detection_recordings` and `raw.bird_detections`: a recording analyzed
again has its detections replaced, never duplicated. Features of a recording missing from `raw.recordings`
are rejected by a foreign key, and then nothing is loaded.

## 8. Model the data with dbt
```bash
uv run --env-file .env --group dbt dbt deps  --project-dir dbt --profiles-dir dbt
uv run --env-file .env --group dbt dbt build --project-dir dbt --profiles-dir dbt
```
`dbt build` loads the 3 seeds (periods of the day, quality and detection
thresholds), builds the staging views and the 2 marts, and runs every data
test, skipping whatever depends on a failed test. The marts leave out
recordings with a quality flag ([docs/quality_review.md](quality_review.md)). Models, periods
of the day and tests: [dbt/README.md](../dbt/README.md).

![dbt lineage graph](img/dbt_lineage.png)

The dashboard at http://localhost:8501 reads the mart with a read-only role
(`dashboard`, allowed to read `marts` only):

![Soundscape dashboard](img/dashboard.png)

## 9. Or let Airflow run the whole pipeline
Steps 5–7 are what the `soundscape_pipeline` DAG runs every day, in order,
retrying each task twice. In http://localhost:8080 turn the DAG on (or use
*Trigger*), then open a run to see each task's state and logs; the `load`
log reports the inserted, updated and unchanged counts. *Clear* re-runs a
date safely: every stage is idempotent.

The full dataset, measured in Docker on an Apple M1 Pro (10 cores, 8 GB for
Docker), with 9,003 recordings new to a database that had 723:

| Task | Time | Result |
|---|---|---|
| `ingest` | 2 min | 9,003 recordings uploaded and registered |
| `detections` | 38 min | 0 failed; 134,144 BirdNET scores ≥ 0.1 |
| `features` | 1 h 55 min | 0 failed (4 processes, ~0.77 s per recording) |
| `load` | 9 s | 9,726 rows of features; detections replaced, not duplicated |
| `dbt build` | 10 s | 89 models and tests pass |

`features` and `detections` run at the same time, so a full run takes about
2 hours. Afterwards 8,890 recordings (91 %) are usable; the quality flags
exclude 836, mostly for low-frequency noise. 6,666 detections pass both
BirdNET thresholds, 197 species. Postgres holds 75 MB; the audio takes 4.5 GB
in S3, on top of the 4.3 GB local copy.

## 10. Verify
```bash
docker compose exec postgres psql -U soundscape -d soundscape \
  -c "SELECT site_code, recorded_at, duration_s FROM raw.recordings ORDER BY recorded_at LIMIT 5;"
uv run pytest                        # all tests, with a coverage report
uv run pytest -m "not integration"   # only the fast tests (no services needed)
uv run --group airflow pytest tests/test_dags.py   # DAGs load (installs Airflow)
```

## 11. AWS emulator

The infrastructure is defined for AWS but validated locally against
[Moto](https://github.com/getmoto/moto), an emulator of the AWS APIs: no AWS
account and no cost. This project has not been deployed to a real AWS account.

```bash
make emulator        # start a fresh Moto on localhost:5001 and create its admin user
make infra-apply     # create the bucket, the pipeline's user and its key with Terraform
make infra-check     # confirm that key can do only what it should
make infra-cycle     # create, destroy with data inside and recreate
make emulator-down   # stop it and erase everything in it
```
Moto keeps everything in memory, so each `make emulator` starts from zero. It
accepts only the 3 requests that create the `terraform-admin` user; after that
every request needs valid keys, so IAM permissions really apply. The admin's
credentials are written to `.env.moto` (git-ignored, owner-only).

To run the pipeline against the emulator, with the pipeline's limited key:
```bash
make sync-storage    # optional: copy the local bucket's objects, same paths
make airflow-cloud   # Airflow's tasks now use the emulator and their own catalog
# trigger soundscape_pipeline in the Airflow UI
make airflow-local   # back to RustFS and the main database
```
Runs against another S3 use a separate database, `soundscape_cloud`, because
`raw.recordings` must describe what is in the bucket in use. Return to local
before stopping the emulator: otherwise the daily DAG would fail.

For a real AWS account the code stays the same; only configuration changes:
copy the two `infra/terraform/envs/aws.*.example` files without `.example`,
put the admin keys in `.env.aws`, and add `ENV=aws` to the commands above.
That path has not been run, since this project has no AWS account yet.

Terraform lives in [`infra/terraform`](../infra/terraform): the same code targets
the emulator or a real account, chosen with `ENV=moto|aws`. The pipeline's key
is created outside Terraform, so the secret never reaches the state.

## 12. Container image

Every push to `main` that passes CI publishes the pipeline as an image on
GitHub Container Registry, tagged with the commit (`sha-<commit>`) and `latest`.
It holds only the pipeline package and its locked dependencies (multi-stage
build, non-root user): about **1.2 GB on disk, ~280 MB to download**, against
3.9 GB for the Airflow image. Most of it is numba/llvmlite, scipy and pyarrow.

```bash
docker run --env-file .env ghcr.io/dres3223/soundscape-data-pipeline ingest   # or features, detections, load
```
Inside Docker, point the settings at reachable hosts (for example
`-e POSTGRES_HOST=... -e S3_ENDPOINT_URL=...`) and mount the recordings for
`ingest` (`-v ...:/data:ro -e INGEST_SOURCE_DIR=/data/...`).
