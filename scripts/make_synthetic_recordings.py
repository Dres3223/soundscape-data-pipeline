"""Write short synthetic recordings, so the pipeline can run without Kaggle.

Used by CI for the end-to-end check (ingest → features → load → dbt build).
Two sites, several periods of the day and two recordings per period, so the
mart has rows with real variability for the dbt tests to check.

Usage:
    uv run python scripts/make_synthetic_recordings.py [folder]
"""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 32000
DEFAULT_FOLDER = Path("data/raw/birdclef/train_soundscapes")

# (site, date, local time, tone in Hz, amplitude)
RECORDINGS = [
    ("T01", "20230422", "060000", 3000, 0.30),  # dawn
    ("T01", "20230423", "063000", 3200, 0.40),  # dawn
    ("T01", "20230422", "120000", 1000, 0.05),  # day
    ("T01", "20230423", "130000", 1100, 0.08),  # day
    ("T01", "20230422", "220000", 5000, 0.50),  # night
    ("T01", "20230423", "230000", 5200, 0.60),  # night
    ("T02", "20230512", "171500", 4000, 0.20),  # dusk
    ("T02", "20230513", "180000", 4200, 0.25),  # dusk
]


def tone(frequency_hz: float, amplitude: float, seconds: float = 2.0) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    noise = np.random.default_rng(0).normal(0, 0.01, t.size)  # a little background
    return (amplitude * np.sin(2 * np.pi * frequency_hz * t) + noise).astype("float32")


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    for site, date, time, frequency_hz, amplitude in RECORDINGS:
        path = folder / f"{site}_{date}_{time}.ogg"
        sf.write(path, tone(frequency_hz, amplitude), SAMPLE_RATE)
    print(f">> Wrote {len(RECORDINGS)} synthetic recordings to {folder}")


if __name__ == "__main__":
    main()
