# Bird detections (BirdNET)

`soundscape.detections` runs BirdNET V2.4 (Kahl et al. 2021, *Ecological
Informatics* 61:101236, doi:10.1016/j.ecoinf.2021.101236) through the
[`birdnet`](https://pypi.org/project/birdnet/) package on every recording.
BirdNET splits each minute into 3-second segments and gives each of 6,522
classes a score from 0 to 1. **The scores are not probabilities, and these
detections are automatic and unvalidated** until P1PDPS-39.

## Files (S3)

`detections/site=<site>/month=<YYYY-MM>/`

**`recordings.parquet`**, one row per recording analyzed, so a recording with
no birds is told apart from one never analyzed:

| Column | Type | Description |
|---|---|---|
| `sha256`, `file_name`, `site_code`, `recorded_at` | | Recording (as in `raw.recordings`) |
| `status` | string | `ok` or `failed` |
| `error` | string | Why it failed, else null |
| `n_detections` | int32 | Rows stored for it in `detections.parquet` |
| `week` | int8 | BirdNET week of the year, 1–48 (4 per month) |
| `model_version` | string | `2.4` |
| `min_confidence` | float32 | Lowest score stored (0.1) |
| `detections_version` | int16 | Version of the code; raising it redoes every recording |
| `detected_at` | timestamp (UTC) | When BirdNET ran |

**`detections.parquet`**, one row per recording, segment and class with a
score of at least 0.1:

| Column | Type | Description |
|---|---|---|
| `sha256`, `file_name`, `site_code`, `recorded_at` | | Recording |
| `start_s`, `end_s` | float32 | Segment within the minute |
| `scientific_name`, `common_name` | string | BirdNET label; a few classes are not birds (e.g. `Engine`) |
| `confidence` | float32 | BirdNET score, 0–1 |
| `geo_score` | float32 | Score of BirdNET's geographic model for the class at the reserve (6.76, −74.21; BirdCLEF 2025 `recording_location.txt`) in that week; null if the model does not know the class |
| `detected_at` | timestamp (UTC) | When BirdNET ran |

Loaded into `raw.detection_recordings` and `raw.bird_detections`; a recording
analyzed again has its detections replaced, never duplicated.

## Which detections count

dbt decides, with the thresholds in `dbt/seeds/detection_thresholds.csv`, so
they change without running BirdNET again:

- `is_confident`: `confidence ≥ 0.5`, a common default.
- `is_expected_here`: `geo_score ≥ 0.03`, the geographic model's default.

`marts.mart_species_by_site_period` keeps only detections with both flags, in
recordings without a quality flag (`is_usable`, see
[quality_review.md](quality_review.md)), and reports in how many of them each
species was detected per site and period of the day.

## What the first run showed (723 recordings, 4 full sites)

- 11,473 scores ≥ 0.1 across 728 classes; 713 reach 0.5 (139 classes), and
  61 classes also pass the geographic filter.
- The geographic filter removes clear errors: species from North America,
  Hawaii or the Amazon, and non-bird classes such as `Engine`.
- **It also removes plausible night birds**, such as Crested Owl (geo score
  0.015) and Choco Screech-Owl (0.014). The geographic model learns from
  eBird, where nocturnal species are under-reported. Results by period
  undercount owls at night.

## Limits

- Unvalidated: P1PDPS-39 compares them with the expert-style labels of El
  Silencio Multi-Taxonomic and calibrates the thresholds.
- `detection_rate` is a naive share of recordings: not an abundance, and not
  corrected for missed or false detections.
- BirdNET V2.4 was trained mostly on focal recordings from the Americas and
  Europe; tropical soundscapes are harder, and insects or frogs can be
  mistaken for birds.
- The model weights are under CC BY-NC-SA 4.0: results derived from them are
  shared for non-commercial use only.
