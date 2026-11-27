# Data source

## Decision
- **Primary (batch):** BirdCLEF+ 2025, Kaggle — https://www.kaggle.com/competitions/birdclef-2025/data
  Recordings from El Silencio Nature Reserve, Middle Magdalena (Colombia). 206 species (birds, amphibians, mammals, insects). OGG audio at 32 kHz.
  License CC BY-NC-SA 4.0: non-commercial use, with attribution. Audio files are not committed to the repository.
- **Secondary (incremental):** Xeno-canto API, filtered to Colombia. Requires an API key.

## What gets downloaded
| File | Use |
|---|---|
| `train.csv`, `taxonomy.csv` | Metadata, in full |
| `train_soundscapes/` | All 9,726 recordings, 4.3 GB (`scripts/download_all.sh`; first a subset of 2 GB) |
| `train_audio/` | Not kept: `download_all.sh` skips it as the archive streams in (reserved for Project 3) |

## Disk budget (12.45 GB free at start)
| Use | Maximum |
|---|---|
| BirdCLEF soundscapes | 4.3 GB, plus 4.5 GB as a copy in S3 (Docker volume) |
| Metadata | < 50 MB |
| Xeno-canto recordings | 500 MB (deleted after feature extraction) |
| Processed data | 200 MB |
| Python environment and Docker | 4 GB |
