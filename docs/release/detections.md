# El Silencio soundscapes: BirdNET bird detections (v$version)

Automatic bird detections by **BirdNET V2.4** in **$n_recordings one-minute
recordings** from **$n_sites sites** of El Silencio Nature Reserve (Middle
Magdalena valley, Colombia), recorded from $first_date to $last_date, with
a comparison against published labels from the same reserve.
**No audio is included.**

**These are automatic detections, not observations.** At the thresholds used
in the summaries, about 8 in 10 species detected in a recording are right,
but only about 1 in 7 species present is found (see *Validation*).

Made by an open pipeline: https://github.com/Dres3223/soundscape-data-pipeline;
this version and the code that made it are the release
`data-v$version` there. A companion dataset,
under CC BY 4.0, holds the acoustic indices and quality flags of the same
recordings.

## Sources

- **Recordings:** the `train_soundscapes` set of BirdCLEF+ 2025 (Kaggle),
  32 kHz mono OGG, published as the original files in: Cañas, J. S., Toro
  Gómez, M. P., Benavides-Lopez, J. L., Rodriguez-Buritica, S., Ulloa, J. S.,
  & Caycedo-Rosales, P. (2025). *El Silencio Soundscapes: A dataset for
  leveraging unlabelled data in machine learning models for passive acoustic
  monitoring* [Data set]. Zenodo. https://doi.org/10.5281/zenodo.17122738
  (CC BY 4.0)
- **Labels used for validation:** Cañas, J. S., Toro Gómez, M. P.,
  Benavides-Lopez, J. L., Rodriguez-Buritica, S., Ulloa, J. S., &
  Caycedo-Rosales, P. (2025). *El Silencio Multi-Taxonomic: A passive acoustic
  monitoring dataset for multi-taxonomic identification in the Middle
  Magdalena, Colombia* [Data set]. Zenodo.
  https://doi.org/10.5281/zenodo.17064353 (CC BY 4.0)
- **Competition:** Cañas, J. S., Kahl, S., Denton, T., Toro-Gómez, M. P.,
  Rodriguez-Buritica, S., Benavides-Lopez, J. L., Ulloa, J. S.,
  Caycedo-Rosales, P., Klinck, H., Goëau, H., Vellinga, W.-P., Planqué, R., &
  Joly, A. (2025). Overview of BirdCLEF+ 2025: Multi-Taxonomic Sound
  Identification in the Middle Magdalena, Colombia. In *Working Notes of CLEF
  2025*, CEUR Workshop Proceedings 4038, 2909–2919.
  https://ceur-ws.org/Vol-4038/paper_232.pdf
- **Model:** Kahl, S., Wood, C. M., Eibl, M., & Klinck, H. (2021). BirdNET: A
  deep learning solution for avian diversity monitoring. *Ecological
  Informatics*, 61, 101236. https://doi.org/10.1016/j.ecoinf.2021.101236.
  Run with the `birdnet` Python package (V2.4 model, LiteRT backend).

Please cite them as well when you use this dataset.

## Files

$files

All files are UTF-8 CSV with a header row. `recording_id` (the SHA-256 of
the audio file) links the tables to each other and to the companion
dataset. Empty cells are missing values. Decimals are given to float32
precision (about 7 significant digits). `SHA256SUMS` checks the files:
`sha256sum -c SHA256SUMS`.

### `recordings_analyzed.csv`: one row per recording

Every recording BirdNET analyzed, so a recording with no detection is told
apart from one never analyzed.

| Column | Description |
|---|---|
| `recording_id`, `file_name`, `site_code` | Recording |
| `recorded_at_local` | Start, from the file name, assumed Colombian local time (UTC-5) |
| `status`, `error` | `ok`, or `failed` with the reason |
| `n_detections` | Rows of this recording in `bird_detections.csv` |
| `week` | BirdNET week of the year (1–48, 4 per month), used by its geographic model |
| `model_version` | BirdNET model version |
| `min_confidence` | Lowest score kept (0.1) |

### `bird_detections.csv`: one row per recording, 3-second segment and class

Every score of at least 0.1: **$n_detections rows**. $n_confident reach
confidence 0.5, and $n_both also pass the geographic filter, for
$n_species classes.

| Column | Description |
|---|---|
| `recording_id`, `site_code`, `recorded_at_local`, `period` | Recording; periods as in the companion dataset |
| `start_s`, `end_s` | Segment within the minute, in seconds |
| `scientific_name`, `common_name` | BirdNET class (eBird 2021 taxonomy). A few classes are not birds, e.g. `Engine`, `Dog` or crickets |
| `confidence` | BirdNET score, 0–1. **Not a probability** |
| `geo_score` | Score of BirdNET's geographic model for the class at the reserve (6.76, −74.21) in that week; empty if the model does not know the class |
| `is_confident` | `confidence ≥ 0.5` |
| `is_expected_here` | `geo_score ≥ 0.03` (BirdNET's default) |

The thresholds are in `detection_thresholds.csv`. Users may choose others:
`validation_curve.csv` shows what each one gives.

### `species_by_site_period.csv`: one row per site, period and species

Only detections with both flags, in recordings without a quality flag (see
the companion dataset). `n_recordings_detected` of the `n_recordings_analyzed`
recordings of that site and period have the species; `detection_rate` is
their ratio; `max_confidence` is the highest score.

### Validation and coverage

- `validation_curve.csv`: precision, recall and F1 with 95 % bootstrap
  intervals, per 3-second segment and per recording, for confidence
  thresholds 0.10–0.95 and geographic thresholds 0, 0.02 and 0.03.
  `species_set = labeled` counts only species present in the labels.
- `validation_species.csv`: the same per species, with Wilson intervals.
- `detections_coverage.csv`: which of the 146 birds of the BirdCLEF+ 2025
  taxonomy are BirdNET classes, and their highest geographic score at the
  reserve.

## Validation

BirdNET was compared with the published labels of El Silencio
Multi-Taxonomic: 747 annotated minutes from 7 other sites of the reserve,
April–May 2023, 88 bird species. Per recording, at confidence 0.5 and
geographic score 0.03:

- **precision 0.80** (95 % CI 0.74–0.84); 0.90 if detections of species
  absent from the labels are taken as right;
- **recall 0.14** (0.12–0.16): BirdNET misses most birds, and 53 of the 88
  species are not found once.

The labels' authors are not stated, so this is BirdNET against published
labels, not a validation by experts.

With the same settings as Funosas et al. (2026, *Ecological Indicators*
182:114550) for tropical moist forest, recall here is lower than their
average. The 0.03 geographic filter lost no correct detection, but it also
drops plausible night birds such as Crested Owl and Choco Screech-Owl,
under-reported in eBird.

Full method and results: `docs/validation.md` in the repository.

## What these data can and cannot say

- **An absence means little.** With recall near 0.14, a species missing from a
  site or period may well have been there. `detection_rate` greatly
  undercounts how often a species is present and is not an abundance.
- **A detection is likely, not certain.** About 1 in 5 is wrong at the chosen
  thresholds; check the per-species figures before relying on one.
- The validation uses other sites, WAV files and only dawn and dusk;
  these detections come from compressed OGG files at all hours.
- Owls and other night birds are undercounted by the geographic filter.
- **Future improvement:** run BirdNET on the original WAV files of the
  Zenodo dataset, not on Kaggle's compressed OGG copies.

## Licence and citation

**CC BY-NC-SA 4.0** (`LICENSE.txt`): BirdNET's model weights are under that
licence, so results made with them are shared for non-commercial use only,
under the same terms. Cite this dataset, plus the sources above, as:

> Martínez, R. (2026). *El Silencio soundscapes: BirdNET bird detections* (Version $version) [Data set].
> https://github.com/Dres3223/soundscape-data-pipeline/releases/tag/data-v$version

Author: Rodrigo Martínez (ORCID 0009-0006-1482-6112).
