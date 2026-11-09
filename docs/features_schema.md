# Audio features: Parquet schema

Written by `uv run python -m soundscape.features`; defined in code as
`FEATURES_SCHEMA` and `FAILED_SCHEMA` in `src/soundscape/features.py`.

## Layout in S3

```
s3://soundscape/
├── features/site=<site>/month=<YYYY-MM>/features.parquet
└── features_failed/failed.parquet
```

- One row per recording, partitioned by site and month (Hive style), so
  query engines skip partitions they do not need. On the full dataset this
  gives ~112 partitions of ~87 rows; partitioning by day would create
  ~1,680 near-empty files.
- Each run rewrites these files whole, so re-running gives the same result.
- `site` and `month` are not stored inside the files: readers recover them
  from the path (`hive_partitioning = true` in DuckDB).

## `features/`

| Column | Type | Unit | Description |
|---|---|---|---|
| `sha256` | string | | Content hash of the audio file; links to `raw.recordings` |
| `file_name` | string | | Original file name |
| `site_code` | string | | Recording site, e.g. `H02` |
| `recorded_at` | timestamp (ms) | assumed local time (UTC-5) | Start of the recording, from the file name |
| `duration_s` | float32 | seconds | Length of the decoded audio |
| `mfcc_mean` | list\<float32\> | dimensionless | Mean of each MFCC over time; `n_mfcc` values |
| `mfcc_std` | list\<float32\> | dimensionless | Standard deviation of each MFCC over time; `n_mfcc` values |
| `spectral_centroid_hz` | float32 | Hz | Mean spectral centroid: where the energy is centred (higher = brighter sound) |
| `spectral_bandwidth_hz` | float32 | Hz | Mean spread of the energy around the centroid |
| `rms_mean` | float32 | amplitude (0–1) | Mean RMS energy of the digital signal; not calibrated, so compare within a site only |
| `zcr_mean` | float32 | fraction (0–1) | Mean zero-crossing rate: share of samples where the signal changes sign |
| `sample_rate_hz` | int32 | Hz | Sample rate used for extraction (`FEATURES_SAMPLE_RATE`) |
| `n_mfcc` | int16 | count | Number of MFCC computed (`FEATURES_N_MFCC`) |
| `extracted_at` | timestamp (µs, UTC) | | When the run that produced the row started |

Frame-level features (MFCC, centroid, bandwidth, RMS, zero-crossing rate)
use librosa's defaults: 2,048-sample frames with a 512-sample hop
(64 ms and 16 ms at 32 kHz).

MFCC are lists so the schema stays the same whatever `n_mfcc` is: changing
the setting changes the length of the lists, not the columns. In DuckDB,
`mfcc_mean[1]` is the first coefficient (lists are 1-indexed).

## `features_failed/`

Recordings that could not be analysed (quarantine). Only the latest run is
kept; an empty file means nothing failed.

| Column | Type | Description |
|---|---|---|
| `sha256` | string | Content hash of the audio file |
| `file_name` | string | Original file name |
| `s3_key` | string | Where the raw file is stored |
| `error` | string | Why it failed, e.g. `audio has no samples` |
| `extracted_at` | timestamp (µs, UTC) | When the run started |

## Querying with DuckDB

```sql
INSTALL httpfs; LOAD httpfs;
CREATE SECRET rustfs (
    TYPE s3, KEY_ID '<S3_ACCESS_KEY>', SECRET '<S3_SECRET_KEY>',
    ENDPOINT 'localhost:9000', URL_STYLE 'path', USE_SSL false
);
SELECT site, month, count(*) AS recordings, avg(spectral_centroid_hz)
FROM read_parquet('s3://soundscape/features/*/*/*.parquet', hive_partitioning = true)
GROUP BY ALL;
```
