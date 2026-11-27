# El Silencio soundscapes: acoustic indices and quality flags (v$version)

Acoustic measurements and quality flags for **$n_recordings one-minute
recordings** from **$n_sites sites** of El Silencio Nature Reserve (Middle
Magdalena valley, Colombia), recorded from $first_date to $last_date. One row
per recording; **no audio is included**.

Made by an open pipeline: https://github.com/Dres3223/soundscape-data-pipeline;
this version and the code that made it are the release
`data-v$version` there.

A companion dataset holds the bird detections made with BirdNET on the same
recordings, under a different licence (CC BY-NC-SA 4.0).

## Source recordings

The audio is the `train_soundscapes` set of the BirdCLEF+ 2025 competition
on Kaggle: 32 kHz mono OGG files. The same recordings are published, as
the original files, in:

> Cañas, J. S., Toro Gómez, M. P., Benavides-Lopez, J. L., Rodriguez-Buritica,
> S., Ulloa, J. S., & Caycedo-Rosales, P. (2025). *El Silencio Soundscapes: A
> dataset for leveraging unlabelled data in machine learning models for
> passive acoustic monitoring* [Data set]. Zenodo.
> https://doi.org/10.5281/zenodo.17122738 (CC BY 4.0)

and described in:

> Cañas, J. S., Kahl, S., Denton, T., Toro-Gómez, M. P., Rodriguez-Buritica,
> S., Benavides-Lopez, J. L., Ulloa, J. S., Caycedo-Rosales, P., Klinck, H.,
> Goëau, H., Vellinga, W.-P., Planqué, R., & Joly, A. (2025). Overview of
> BirdCLEF+ 2025: Multi-Taxonomic Sound Identification in the Middle
> Magdalena, Colombia. In *Working Notes of CLEF 2025*, CEUR Workshop
> Proceedings 4038, 2909–2919. https://ceur-ws.org/Vol-4038/paper_232.pdf

Please cite them as well when you use this dataset.

## Files

$files

All files are UTF-8 CSV with a header row. `recording_id` (the SHA-256 of
the audio file) links every table. Empty cells are missing values.
Decimals are given to float32 precision (about 7 significant digits).
`SHA256SUMS` checks the files: `sha256sum -c SHA256SUMS`.

### `recordings.csv`: one row per recording

| Column | Description |
|---|---|
| `recording_id` | SHA-256 of the audio file |
| `file_name` | File name in the source: `<site>_<YYYYMMDD>_<HHMMSS>.ogg` |
| `site_code` | Recording site, e.g. `H02` |
| `recorded_at_local` | Start of the recording, from the file name, assumed to be Colombian local time (UTC-5) |
| `period` | Period of the day: `dawn` (05–07 h), `day` (08–16 h), `dusk` (17–18 h) or `night` (19–04 h); see `day_periods.csv` |
| `duration_s` | Length in seconds |
| `sample_rate_hz` | Sample rate of the file |
| `is_usable` | `true` when no quality flag is raised; the site summaries use only these |
| `is_heavy_rain` | `rain_band_psd_db` above its threshold |
| `is_low_freq_noise` | `low_freq_energy_ratio` above its threshold: wind, a stream, an engine or handling |
| `is_clipped` | `clipping_fraction` above its threshold |
| `has_dropout` | `longest_zero_run_s` above its threshold |

Thresholds: `quality_thresholds.csv`.

### `acoustic_indices.csv`: one row per recording

| Column | Unit | Description |
|---|---|---|
| `recording_id`, `site_code`, `recorded_at_local` | | As in `recordings.csv` |
| `duration_s` | s | Length of the decoded audio |
| `spectral_centroid_hz` | Hz | Mean spectral centroid: where the energy is centred |
| `spectral_bandwidth_hz` | Hz | Mean spread of the energy around the centroid |
| `rms` | 0–1 | Mean RMS amplitude of the digital signal |
| `rms_dbfs` | dBFS | `rms` in decibels relative to full scale |
| `zero_crossing_rate` | 0–1 | Share of samples where the signal changes sign |
| `aci` | | Acoustic Complexity Index |
| `adi` | | Acoustic Diversity Index (Shannon, 1 kHz bands) |
| `aei` | 0–1 | Acoustic Evenness Index (Gini, 1 kHz bands) |
| `bi` | | Bioacoustic Index, 2–8 kHz |
| `ndsi` | −1–1 | Normalized Difference Soundscape Index: 2–8 kHz against 1–2 kHz |
| `ht`, `hf` | 0–1 | Temporal and spectral entropy |
| `bgnt_db` | dB | Background noise of the waveform, relative to full scale |
| `snrt_db` | dB | Signal-to-noise ratio of the waveform |
| `clipping_fraction` | 0–1 | Share of samples at or above 0.999 of full scale |
| `longest_zero_run_s` | s | Longest stretch of exact digital zeros |
| `low_freq_energy_ratio` | 0–1 | Share of the energy below 200 Hz |
| `rain_band_psd_db` | dB | Mean power in 600–1200 Hz, where rain is most prominent |
| `rain_band_snr` | | Mean over standard deviation of that band's power over time |
| `mfcc_mean_01`…`mfcc_mean_20`, `mfcc_std_01`…`mfcc_std_20` | | Mean and standard deviation over time of each of 20 MFCC |
| `analysis_sample_rate_hz` | Hz | Sample rate used for the calculation |

### `soundscape_by_site_period.csv`: one row per site and period

Usable recordings only: `n_recordings` of them, `n_excluded` left out for a
quality flag. Means (`avg_*`) and standard deviations (`stddev_*`) of the
measures above; `rms_dbfs_vs_site_avg`, the period's level minus the site's
average; `loudness_rank_in_site`, 1 for the loudest period of the site;
`*_change_vs_previous`, the change from the previous period of the day
(empty for dawn).

### `quality_thresholds.csv`, `day_periods.csv`

The thresholds behind the quality flags, and the hour-to-period table.

## Method

- **Frame-level features** (MFCC, centroid, bandwidth, RMS, zero-crossing
  rate): librosa, default settings (2,048-sample frames, 512 hop), averaged
  over the minute.
- **Ecoacoustic indices:** scikit-maad (Ulloa et al. 2021, *Methods in
  Ecology and Evolution*, doi:10.1111/2041-210X.13711), default settings
  except a fixed spectrogram (1,024-sample Hann window, 512 overlap) and the
  high band capped at 16 kHz. They are empty for pure digital silence.
- **Quality flags:** thresholds set by the author on spectrograms of 40
  recordings from 4 sites, following Bedoya et al. (2017, *Ecological
  Indicators*, doi:10.1016/j.ecolind.2016.12.018) for rain. Not reviewed by
  an expert. Here $n_usable recordings ($share_usable %) are usable and
  $n_excluded are flagged, most for low-frequency noise.
- Exact code, settings and tests: the repository above
  (`src/soundscape/features.py`, `dbt/`, `docs/features_schema.md`,
  `docs/quality_review.md`).

## What these data can and cannot say

- **Indices are not measures of biodiversity.** Rain, wind, insects, frogs or
  the recorder change them, and their bands were not designed for this
  forest. With these settings ACI and ADI barely vary between recordings.
- **Levels are not calibrated:** compare them within a site, not between sites.
- **Times are assumed** to be local (UTC-5), and the periods of the day are a
  working choice.
- **One season only:** about 38 days of April–May 2023.
- The quality flags are a documented first filter, not ground truth: light
  rain is not detected, and low-frequency noise has several possible causes.
- **Future improvement:** compute the measures on the original WAV files of
  the Zenodo dataset, not on Kaggle's compressed OGG copies.

## Licence and citation

**CC BY 4.0** (`LICENSE.txt`). Cite this dataset, plus the sources above, as:

> Martínez, R. (2026). *El Silencio soundscapes: acoustic indices and quality flags* (Version $version) [Data set].
> https://github.com/Dres3223/soundscape-data-pipeline/releases/tag/data-v$version

Author: Rodrigo Martínez (ORCID 0009-0006-1482-6112).
