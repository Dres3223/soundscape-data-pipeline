# Quality flags: how the thresholds were set

The pipeline computes five quality measures per recording
([features_schema.md](features_schema.md)) and dbt turns four of them into
flags with the thresholds in `dbt/seeds/qc_thresholds.csv`. A recording with
any flag is kept in `staging.stg_audio_features` (`is_usable = false`) but
left out of the mart, which reports how many were excluded (`n_excluded`).

**Who reviewed:** the author, who is not an ecoacoustics expert. No external
expert checked these flags. Treat them as a documented first filter, not as
ground truth.

## Method

1. Started from the literature: rain is most prominent in 600–1200 Hz and is
   detected by high power plus steadiness in that band (Bedoya et al. 2017,
   *Ecological Indicators*, doi:10.1016/j.ecolind.2016.12.018; Sánchez-Giraldo
   et al. 2020, *Remote Sensing in Ecology and Conservation*,
   doi:10.1002/rse2.162). For wind no validated cutoff was found; energy
   concentrated in low frequencies is the usual cue.
2. Looked at the distribution of each measure on the 723 recordings.
3. Drew spectrograms of 40 recordings: the 8 highest by rain power, the 8 most
   steady in the rain band, the 8 with most low-frequency energy, the 6
   quietest and 10 at random (seed 42). Sheets and measures:
   [`img/quality/`](img/quality/), reproducible with
   `scripts/quality_review_sheets.py`.

## What the review found

| Measure | Seen in the spectrograms | Decision |
|---|---|---|
| `rain_band_psd_db` | The 4 highest (16.5–21.2 dB, all near −15 to −21 dBFS) show broadband energy with dense vertical streaks: heavy rain. The next ones (5.5–8.3 dB) are loud insect or frog choruses. No recording falls between 8.3 and 16.5 dB. | Flag above **12 dB** (the middle of that gap). 4 recordings. |
| `rain_band_snr` | Its highest values are steady animal choruses (horizontal bands), not rain. | **Not used** for any flag; kept as a measure. Light rain is therefore not detected. |
| `low_freq_energy_ratio` | The highest (0.87–0.95) are quiet recordings whose energy sits below a few hundred Hz; some show rumble over a stretch of the minute. Consistent with wind, but it cannot be told apart from a stream, an engine or handling. | Flag above **0.5** as `is_low_freq_noise` (not "wind"). 55 recordings. |
| Quietest (−54 to −55 dBFS) | A flat noise floor with faint calls: quiet moments, not failures. | **No "weak signal" flag**, unlike first planned. |
| `clipping_fraction` | Maximum 0.09 % of samples; nothing audible. | Flag above 0.1 %. 0 recordings. |
| `longest_zero_run_s` | Always 0. | Flag above 0.1 s. 0 recordings. |

## Effect

On the 723 reviewed recordings, 59 (8 %) are excluded: 4 for heavy rain, 55
for low-frequency noise, none for both. The exclusions are not even: **site H24
loses 38 of 178**, and 28 of its 70 daytime recordings. Comparisons that
involve H24 during the day rest on fewer recordings and may be biased towards
calm moments.

## Effect on the full dataset

The same thresholds, applied to all 9,726 recordings (56 sites) without a
new review of spectrograms:

- **836 recordings (8.6 %) are excluded**: 801 for low-frequency noise, 43
  for heavy rain and 11 for clipping (some have more than one flag). None has
  a dropout.
- **The rain gap is gone.** 61 recordings fall between 8.3 and 16.5 dB, and
  the values around the 12 dB threshold are continuous (23 between 10 and
  12 dB, 14 between 12 and 14 dB). The threshold is still the one chosen on
  the sample, but recordings just above and below it were not looked at.
- **Clipping appears**: 11 recordings pass 0.1 % (at most 1.4 % of samples).
  They were not reviewed either.
- **Exclusions are very uneven.** 32 of 56 sites lose under 5 % (the median
  site 4 %, and 3 sites none), but 7 sites lose more than 20 %: H31 (76 of
  175), H27 (71 of 175), H32 (66 of 175), H03 (54 of 179), H04 (48 of 176),
  H14 (41 of 174) and H24 (38 of 178). Almost all of it is low-frequency noise during the day: H27
  keeps 11 of its 68 daytime recordings, H31 15 of 69 and H32 19 of 71. For
  these sites, daytime averages describe the calm moments, not a typical
  day.

The mart reports `n_excluded` for every site and period, and the dashboard
shows it, so these gaps stay visible.

**Time of day.** The file names do not say their time zone; the pipeline
assumes Colombian local time (UTC-5). The detections agree: confident BirdNET
species per recording jump from 0.08 at 4 h to 0.37 at 5 h and fall from
0.16 at 18 h to 0.05 at 19 h, around sunrise and sunset at the reserve. In
UTC the dawn chorus would appear five hours later.

## Limits

- One non-expert reviewer, 40 recordings, no listening test with headphones.
- Light rain and moderate wind go undetected.
- The 0.5 low-frequency threshold is a judgment call: the distribution has no
  clear gap (median 0.02, 95th percentile 0.64).
- Thresholds were set on 4 sites in April–May 2023 and may not transfer to
  other sites or seasons. To change one, edit the seed and run `dbt build`.
