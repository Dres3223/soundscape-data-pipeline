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
- Runs are incremental: only recordings without up-to-date features are analyzed,
  and only their partitions are rewritten, keeping the rows already there.
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
| `aci` | float32 | | Acoustic Complexity Index: change of intensity between consecutive moments, summed over frequencies |
| `adi` | float32 | | Acoustic Diversity Index: Shannon diversity of energy across 1 kHz bands |
| `aei` | float32 | 0–1 | Acoustic Evenness Index: Gini coefficient across 1 kHz bands (higher = more concentrated) |
| `bi` | float32 | | Bioacoustic Index: energy above the quietest level in 2–8 kHz |
| `ndsi` | float32 | −1–1 | Normalized Difference Soundscape Index: 2–8 kHz ("biophony") against 1–2 kHz ("anthropophony") |
| `ht` | float32 | 0–1 | Temporal entropy: evenness of energy over time |
| `hf` | float32 | 0–1 | Spectral entropy: evenness of energy over frequency |
| `bgnt_db` | float32 | dB | Background noise of the waveform, relative to full scale; not calibrated |
| `snrt_db` | float32 | dB | Signal-to-noise ratio of the waveform |
| `clipping_fraction` | float32 | 0–1 | Share of samples at or above 0.999 of full scale |
| `longest_zero_run_s` | float32 | seconds | Longest stretch of exact digital zeros (dropouts) |
| `low_freq_energy_ratio` | float32 | 0–1 | Share of the energy below 200 Hz (wind or other low-frequency noise) |
| `rain_band_psd_db` | float32 | dB | Mean power in 600–1200 Hz, the band where rain is most prominent (Bedoya et al. 2017); not calibrated |
| `rain_band_snr` | float32 | | Mean over standard deviation of that band's power over time |
| `sample_rate_hz` | int32 | Hz | Sample rate used for extraction (`FEATURES_SAMPLE_RATE`) |
| `n_mfcc` | int16 | count | Number of MFCC computed (`FEATURES_N_MFCC`) |
| `features_version` | int16 | | Version of the calculation; raised in the code when it changes, so every recording is redone |
| `extracted_at` | timestamp (µs, UTC) | | When the run that computed the row started; kept while the row stays up to date |

Ecoacoustic indices come from [scikit-maad](https://scikit-maad.github.io/)
(Ulloa et al. 2021, doi:10.1111/2041-210X.13711), with its default settings
except for a fixed spectrogram (1,024-sample Hann window, 512 overlap) and the
high band capped at 16 kHz; the exact settings are `SPECTROGRAM` and `BANDS_HZ`
in `src/soundscape/features.py`. They are null for pure digital silence, where
several are undefined. **They are not measures of biodiversity:** rain, wind,
insects or the recorder can change them, and their bands were not designed
for this tropical forest.

Quality measures are only numbers; dbt turns them into flags with the
thresholds in `dbt/seeds/qc_thresholds.csv`. How those thresholds were set,
and their limits: [quality_review.md](quality_review.md).

On the 723 recordings processed so far (4 full sites), ACI stays around 300
and ADI close to its maximum (~2.3) in every site and period: with these
settings they barely separate recordings. BI and NDSI vary much more.

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
