# How well BirdNET does at El Silencio

BirdNET's detections (see [detections_schema.md](detections_schema.md)) were
compared with the published labels of **El Silencio Multi-Taxonomic** (Cañas
et al., Zenodo, doi:10.5281/zenodo.17064353, CC BY 4.0). This is **BirdNET
against published labels, not a validation by experts**: the dataset does not
say who made the labels, and nobody in this project listened to the
recordings.

Made with `uv run python -m soundscape.validation` (`src/soundscape/validation.py`);
results in [validation_curve.csv](validation_curve.csv) and
[validation_species.csv](validation_species.csv).

## Method

- **Recordings:** the 770 one-minute WAV files of 7 sites (H23, H64, H75,
  H80, H82, H87, H96), April–May 2023, at dawn and dusk. They are not the 4
  sites the pipeline processes. BirdNET V2.4 ran on them with the pipeline's
  settings (`detections.detect`, scores ≥ 0.1). The 747 recordings with at
  least one label of any group are evaluated; 511 of them have birds.
- **Labels:** 10,349 bird boxes in time and frequency. Kept: the 9,319 named
  to species, 88 species. Five names were mapped to BirdNET's taxonomy
  (eBird 2021): three misspellings (*Baryptengus*, *griceiceps*, *Zimerius*),
  *Saltator olivaceus* → *S. olivascens*, and *Schiffornis turdinus* →
  *S. stenorhyncha* (eBird split the species). One, *Chrysuronia goudoti*, is
  not a BirdNET class.
- **Unidentified birds:** a BirdNET detection of a species in a 3-second
  segment where the labels only have an unidentified bird or a bird sonotype
  may be right, so it is left out, neither hit nor error. BirdNET's non-bird
  classes (`Engine`, `Dog`, crickets…) are left out too.
- **Two levels:**
  - *segment*: is the species labeled in the 3-second segment where BirdNET
    detects it?
  - *recording*: is a species BirdNET detects in a minute labeled anywhere
    in that minute? This is the level of `mart_species_by_site_period`.
- **Measures:** precision (share of detections that are right), recall (share
  of labeled species found) and F1, for confidence thresholds 0.10–0.95 and
  geographic thresholds 0, 0.02 and 0.03. 95 % intervals by bootstrap over
  recordings (1,000 resamples); per species, Wilson intervals.

## Results

Per recording, with the geographic filter at 0.03:

| Confidence | Precision [95 % CI] | Recall [95 % CI] | F1 |
|---|---|---|---|
| 0.10 | 0.38 [0.35–0.41] | 0.31 [0.28–0.33] | 0.34 |
| 0.15 | 0.47 [0.43–0.50] | 0.26 [0.24–0.29] | 0.34 |
| 0.30 | 0.65 [0.60–0.69] | 0.20 [0.18–0.22] | 0.30 |
| **0.50** | **0.80 [0.74–0.84]** | **0.14 [0.12–0.16]** | 0.24 |
| 0.70 | 0.87 [0.80–0.92] | 0.08 [0.07–0.10] | 0.15 |
| 0.90 | 0.93 [0.85–0.98] | 0.03 [0.02–0.04] | 0.06 |

- **BirdNET misses most birds.** At 0.5 it finds 14 % of the labeled
  species–recording pairs, and never more than 31 %. 53 of the 88 species are
  not found once at 0.5; Crimson-backed Tanager (*Ramphocelus dimidiatus*),
  labeled in 29 recordings, and Ruddy Ground Dove (*Columbina talpacoti*), in
  44, are not detected once at 0.5. Per segment recall is lower still (0.06 at 0.5,
  0.17 at 0.1), as many labeled calls are short or faint.
- **When it names a labeled species, it is nearly always right**: at 0.5,
  Pale-vented Pigeon 0.96 (22 of 23), Yellow-crowned Amazon 0.97, Colombian
  Chachalaca 0.93, Little Tinamou and Black-bellied Wren 1.0. Recall per
  species, among those labeled in at least 10 recordings, goes from 0 to 0.53
  (Colombian Chachalaca).
- **About half the errors are species absent from the labels** (32 of 57 at
  0.5), such as Northern Screamer (*Chauna chavaria*), Palm Tanager or
  Chestnut-winged Chachalaca. Some may be real birds the annotators left out,
  so precision lies between two bounds: 0.80 if every such detection is
  wrong, 0.90 if every one is right (`species_set = labeled` in the curve).
- **The geographic filter only removes errors here.** With 0.02 or 0.03 not
  one correct detection is lost, and 0.03 removes more errors (at 0.5:
  precision 0.54 without the filter, 0.78 with 0.02, 0.80 with 0.03).

## Thresholds chosen

`dbt/seeds/detection_thresholds.csv` keeps **confidence ≥ 0.5** and
**geographic score ≥ 0.03**, now set from these data:

- The F1 curve is flat between 0.10 and 0.20 (0.34) and peaks at 0.15, but
  there one species in two in the mart would be false (precision 0.47).
- 0.5 gives precision 0.80–0.90 per recording at the cost of recall: a
  species in the mart was most likely there, while an absent species may
  well have been missed. 0.55 is the lowest threshold with precision ≥ 0.80
  (0.803), in practice the same.
- Users wanting more recall can choose another row of
  `validation_curve.csv`, change the seed and run `dbt build`.

## Compared with the global assessment

Funosas et al. (2026, *Ecological Indicators* 182:114550) evaluated BirdNET
V2.4 on 4,224 expert-labeled minutes from 67 sites. In tropical moist broadleaf
forest, at confidence 0.1 and geographic threshold 0.02, they report
precision 0.66 and recall 0.41 per vocalization. Here, per segment with the
same settings, precision is 0.40 (0.73 counting only labeled species) and
recall 0.17. BirdNET does worse at El Silencio than their average, mainly in
recall. Their units are single calls and ours are 3-second segments, so the
numbers are close but not identical in meaning.

## Limits

- The labels' authors are not stated, and the labels may not include every
  bird: precision may be underestimated (see the two bounds above).
- 7 sites, April–May 2023, dawn and dusk only. Night birds are nearly absent
  from the labels, so the geographic filter's effect on owls (see
  [detections_schema.md](detections_schema.md)) is not tested.
- These recordings are 48 kHz WAV; the pipeline analyzes the BirdCLEF 2025
  OGG files of other sites. Same model and settings, but site and format
  differ.
- Per-species figures rest on few recordings for most species: see the
  intervals in `validation_species.csv` before using one.
- `detection_rate` in the mart is still a naive share of recordings: with
  recall near 0.14, it greatly undercounts how often a species is present.

## Reproduce

```bash
uv run python -m soundscape.validation data/validation docs
```

Downloads the labels and, one site at a time, each zip (~500 MB), runs
BirdNET, keeps only the detections and deletes the audio (needs ~1.2 GB of
free disk; ~10 minutes on an M1 Pro). Detections are kept in
`data/validation/` so a second run only recomputes the measures.
