# Bird detections (BirdNET)

`soundscape.detections` runs BirdNET V2.4 (Kahl et al. 2021, *Ecological
Informatics* 61:101236, doi:10.1016/j.ecoinf.2021.101236) through the
[`birdnet`](https://pypi.org/project/birdnet/) package on every recording.
BirdNET splits each minute into 3-second segments and gives each of 6,522
classes a score from 0 to 1. **The scores are not probabilities, and these
detections are automatic.** Compared with published labels at El Silencio,
at the thresholds below about 8 in 10 species detected in a recording are
right, but only about 1 in 7 labeled species is found
([validation.md](validation.md)).

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

- `is_confident`: `confidence ≥ 0.5`: per recording, precision 0.80–0.90
  and recall 0.14 in [validation.md](validation.md), which explains the
  choice.
- `is_expected_here`: `geo_score ≥ 0.03`, the geographic model's default;
  in the validation it removed errors and no correct detection.

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

## Which of the dataset's birds BirdNET covers

[`detections_coverage.csv`](detections_coverage.csv) matches the 146 birds of
the BirdCLEF 2025 taxonomy (`taxonomy.csv`) with BirdNET's classes, and gives
each one's highest geographic score at the reserve in the weeks of the
recordings (15–20). Made with `scripts/birdnet_coverage.py`.

- **145 of 146 are BirdNET classes**, all by scientific name. Not covered:
  Shining-green Hummingbird (*Chrysuronia goudoti*), which BirdNET can never
  detect.
- **The names do not always mean the same species.** The dataset follows
  iNaturalist, BirdNET follows eBird. *Schiffornis turdina* is one broad
  species in the first and is split in the second: BirdNET's
  *S. turdina* is an Amazonian bird (geographic score 0.0), and the one
  expected in the Magdalena valley is *S. stenorhyncha* (0.056). Comparisons
  with the dataset's labels must map such cases by hand.
- **The geographic filter (0.03) would drop 5 of the 145**, even though they
  are listed for the reserve: Spectacled Owl (0.029), Striped Owl (0.022),
  Red-and-green Macaw (0.029), Royal Flycatcher (0.024) and *S. turdina*.
  With 0.02, the value used by Funosas et al. (2026, *Ecological Indicators*
  182:114550), only *S. turdina* would. In the validation the 0.03 filter
  lost no correct detection, so it stays ([validation.md](validation.md)); the
  owls are not tested there.

## Speed

On an Apple M1 Pro (10 cores) with the LiteRT backend, BirdNET takes
**0.11 s per one-minute recording** (two batches of 100 random recordings:
0.107 s each). The 9,726 BirdCLEF 2025 `train_soundscapes` would take
about 18 minutes, plus reading them from S3; slower machines, or Docker on a
Mac, take longer. In Airflow, in Docker on the same Mac and while `features`
used 4 cores, the 9,003 recordings new to the full run took 38 minutes
(0.25 s each), with no failure.

## Limits

- Checked against published labels, not by experts, and on other sites:
  see the limits in [validation.md](validation.md). BirdNET misses most birds
  there (recall 0.14 at the chosen thresholds).
- `detection_rate` is a naive share of recordings: not an abundance, and not
  corrected for missed or false detections; with such low recall it greatly
  undercounts how often a species is present.
- BirdNET V2.4 was trained mostly on focal recordings from the Americas and
  Europe; tropical soundscapes are harder, and insects or frogs can be
  mistaken for birds.
- The model weights are under CC BY-NC-SA 4.0: results derived from them are
  shared for non-commercial use only.
