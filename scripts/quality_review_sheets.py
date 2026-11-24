"""Spectrogram sheets for the visual review of the quality measures.

Picks 40 recordings (highest rain measures, highest low-frequency share,
quietest, and a random control set), draws each one as a spectrogram with its
measures, 10 per sheet, and writes sample.csv with the selection.
See docs/quality_review.md for the review made with them.

Usage (from the project root, with the services up):
    uv run python scripts/quality_review_sheets.py \\
        data/raw/birdclef/train_soundscapes <output folder>
"""

import csv
import sys
from pathlib import Path

import librosa
import librosa.display
import matplotlib
import numpy as np
from psycopg.rows import dict_row

from soundscape.config import Settings
from soundscape.storage import pg_connect

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SAMPLE_SIZE = 40
PER_SHEET = 10
COLUMNS = [
    "rms_dbfs",
    "rain_band_psd_db",
    "rain_band_snr",
    "low_freq_energy_ratio",
    "clipping_fraction",
    "longest_zero_run_s",
]
QUERY = """
SELECT file_name,
       20 * log(greatest(rms_mean, 1e-10)::numeric)::float AS rms_dbfs,
       rain_band_psd_db, rain_band_snr, low_freq_energy_ratio,
       clipping_fraction, longest_zero_run_s
FROM raw.audio_features
"""


def pick(rows: list[dict]) -> list[tuple[str, dict]]:
    """The extremes of each measure, then random recordings as a control."""

    def top(key: str, n: int, highest: bool = True) -> list[dict]:
        return sorted(rows, key=lambda r: r[key] or 0, reverse=highest)[:n]

    groups = [
        ("rain_psd", top("rain_band_psd_db", 8)),
        ("rain_snr", top("rain_band_snr", 8)),
        ("low_freq", top("low_freq_energy_ratio", 8)),
        ("quiet", top("rms_dbfs", 6, highest=False)),
    ]
    chosen, seen = [], set()
    for group, items in groups:
        for row in items:
            if row["file_name"] not in seen:
                seen.add(row["file_name"])
                chosen.append((group, row))
    pool = [row for row in rows if row["file_name"] not in seen]
    rng = np.random.default_rng(42)
    for i in rng.choice(len(pool), size=SAMPLE_SIZE - len(chosen), replace=False):
        chosen.append(("random", pool[i]))
    return chosen


def draw(chosen: list[tuple[str, dict]], audio_dir: Path, out: Path) -> None:
    for start in range(0, len(chosen), PER_SHEET):
        fig, axes = plt.subplots(5, 2, figsize=(14, 15))
        batch = enumerate(chosen[start : start + PER_SHEET], start + 1)
        for ax, (i, (group, row)) in zip(axes.flat, batch, strict=False):
            audio, sr = librosa.load(audio_dir / row["file_name"], sr=None)
            stft = np.abs(librosa.stft(audio, n_fft=1024, hop_length=512))
            db = librosa.amplitude_to_db(stft, ref=np.max)
            librosa.display.specshow(
                db, sr=sr, hop_length=512, x_axis="s", y_axis="hz",
                ax=ax, cmap="magma", vmin=-80, vmax=0,
            )  # fmt: skip
            ax.set_ylim(0, 16000)
            ax.set_title(
                f"#{i} {group} {row['file_name'][:-4]}"
                f" | rain psd {row['rain_band_psd_db']:.0f}"
                f" snr {row['rain_band_snr']:.1f}"
                f" | low {row['low_freq_energy_ratio']:.2f}"
                f" | {row['rms_dbfs']:.0f} dBFS",
                fontsize=8,
            )
            ax.set_xlabel("")
            ax.set_ylabel("")
        fig.tight_layout()
        fig.savefig(out / f"sheet_{start // PER_SHEET + 1}.png", dpi=55)
        plt.close(fig)


def main() -> None:
    audio_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    with pg_connect(Settings(), row_factory=dict_row) as conn:
        rows = conn.execute(QUERY).fetchall()

    chosen = pick(rows)
    with open(out / "sample.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "group", "file_name", *COLUMNS])
        for i, (group, row) in enumerate(chosen, 1):
            writer.writerow([i, group, row["file_name"], *(row[c] for c in COLUMNS)])
    draw(chosen, audio_dir, out)
    print(f"{len(chosen)} recordings in {out}")


if __name__ == "__main__":
    main()
