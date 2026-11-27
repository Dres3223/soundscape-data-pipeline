"""Export the derived dataset for publication: tables, README, licence, checksums.

Usage:
    uv run python -m soundscape.export [out_dir]   # default: data/release

Reads the dbt models, so run `dbt build` first. Writes two folders, one per
licence:

    indices/     recordings, quality flags and acoustic indices (CC BY 4.0)
    detections/  BirdNET detections and the species mart (CC BY-NC-SA 4.0,
                 the licence of BirdNET's model weights)

Each folder gets its README (docs/release/<folder>.md, with the counts filled
in), a LICENSE.txt and SHA256SUMS, and is zipped as
soundscape-<folder>-v<VERSION>.zip for a GitHub release. No audio is
exported. How to publish: docs/release/PUBLISHING.md.
"""

import csv
import hashlib
import logging
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from string import Template

import numpy as np

from soundscape.config import Settings
from soundscape.storage import pg_connect

log = logging.getLogger("soundscape.export")

VERSION = "1.0.0"
DOCS = Path(__file__).resolve().parents[2] / "docs"

LICENCES = {
    "indices": (
        "Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "https://creativecommons.org/licenses/by/4.0/legalcode",
    ),
    "detections": (
        "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International "
        "(CC BY-NC-SA 4.0)",
        "https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode",
    ),
}

MEASURES = [
    "duration_s",
    "spectral_centroid_hz",
    "spectral_bandwidth_hz",
    "rms",
    "rms_dbfs",
    "zero_crossing_rate",
    "aci",
    "adi",
    "aei",
    "bi",
    "ndsi",
    "ht",
    "hf",
    "bgnt_db",
    "snrt_db",
    "clipping_fraction",
    "longest_zero_run_s",
    "low_freq_energy_ratio",
    "rain_band_psd_db",
    "rain_band_snr",
]


def mfcc_columns(n_mfcc: int) -> list[str]:
    """One column per coefficient: CSV has no arrays."""
    return [
        f"{stat}[{i}] AS mfcc_{stat.removeprefix('mfcc_')}_{i:02d}"
        for stat in ("mfcc_mean", "mfcc_std")
        for i in range(1, n_mfcc + 1)
    ]


def queries(n_mfcc: int) -> dict[str, dict[str, str]]:
    """SQL of every table, by folder and file name."""
    by_time = "site_code, recorded_at_local"
    return {
        "indices": {
            "recordings.csv": """
                SELECT r.recording_id, r.file_name, r.site_code,
                       r.recorded_at_local, f.period, r.duration_s,
                       r.sample_rate_hz, f.is_usable, f.is_heavy_rain,
                       f.is_low_freq_noise, f.is_clipped, f.has_dropout
                FROM staging.stg_recordings r
                JOIN staging.stg_audio_features f USING (recording_id)
                ORDER BY r.site_code, r.recorded_at_local, r.file_name""",
            "acoustic_indices.csv": f"""
                SELECT recording_id, site_code, recorded_at_local,
                       {", ".join(MEASURES + mfcc_columns(n_mfcc))},
                       sample_rate_hz AS analysis_sample_rate_hz
                FROM staging.stg_audio_features
                ORDER BY {by_time}, recording_id""",
            "soundscape_by_site_period.csv": """
                SELECT * FROM marts.mart_soundscape_by_point_period
                ORDER BY site_code, period_order""",
            "quality_thresholds.csv": """
                SELECT * FROM staging.qc_thresholds ORDER BY flag""",
            "day_periods.csv": """
                SELECT * FROM staging.day_periods ORDER BY hour_of_day""",
        },
        "detections": {
            "recordings_analyzed.csv": """
                SELECT d.sha256 AS recording_id, r.file_name, r.site_code,
                       r.recorded_at_local, d.status, d.error, d.n_detections,
                       d.week, d.model_version, d.min_confidence
                FROM raw.detection_recordings d
                JOIN staging.stg_recordings r ON r.recording_id = d.sha256
                ORDER BY r.site_code, r.recorded_at_local, r.file_name""",
            "bird_detections.csv": f"""
                SELECT recording_id, site_code, recorded_at_local, period,
                       start_s, end_s, scientific_name, common_name,
                       confidence, geo_score, is_confident, is_expected_here
                FROM staging.stg_bird_detections
                ORDER BY {by_time}, recording_id, start_s, scientific_name""",
            "species_by_site_period.csv": """
                SELECT * FROM marts.mart_species_by_site_period
                ORDER BY site_code, period_order, scientific_name""",
            "detection_thresholds.csv": """
                SELECT * FROM staging.detection_thresholds ORDER BY flag""",
        },
    }


# Copied as they are from docs/: validation and coverage of BirdNET
DOC_TABLES = {
    "detections": [
        "validation_curve.csv",
        "validation_species.csv",
        "detections_coverage.csv",
    ]
}


def cell(value) -> str:
    """CSV text of a value: the same on every run and every machine."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not np.isfinite(value):
            return ""
        # Stored as float32: its shortest exact form (0.3, not 0.30000001...)
        return np.format_float_positional(np.float32(value), trim="-")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def write_csv(path: Path, columns: list[str], rows) -> int:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(columns)
        count = 0
        for row in rows:
            writer.writerow([cell(value) for value in row])
            count += 1
    return count


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(folder: Path) -> None:
    """SHA256SUMS in the format of `sha256sum -c`."""
    lines = [
        f"{sha256_of(path)}  {path.name}"
        for path in sorted(folder.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def zip_folder(folder: Path, path: Path) -> None:
    """Zip the folder's files: fixed dates and order, so the same files give
    the same zip on every run."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(folder.iterdir()):
            info = zipfile.ZipInfo(f"{folder.name}/{file.name}", (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, file.read_bytes())


def file_table(folder: Path, rows: dict[str, int]) -> str:
    """Markdown table of the data files, their rows and sizes."""
    lines = ["| File | Rows | Size |", "|---|---|---|"]
    for name in sorted(rows):
        size = (folder / name).stat().st_size
        shown = f"{size / 1024:,.0f} KB" if size >= 1024 else f"{size} bytes"
        lines.append(f"| `{name}` | {rows[name]:,} | {shown} |")
    return "\n".join(lines)


def render(template: Path, values: dict) -> str:
    """Fill a README template; a missing value is an error, not a blank."""
    return Template(template.read_text(encoding="utf-8")).substitute(values)


@dataclass
class Summary:
    n_recordings: int
    n_sites: int
    first_date: date
    last_date: date
    n_usable: int
    n_detections: int
    n_confident: int
    n_both: int
    n_species: int

    def values(self) -> dict:
        return {
            "version": VERSION,
            "n_recordings": f"{self.n_recordings:,}",
            "n_sites": self.n_sites,
            "first_date": self.first_date.isoformat(),
            "last_date": self.last_date.isoformat(),
            "n_usable": f"{self.n_usable:,}",
            "share_usable": f"{100 * self.n_usable / max(1, self.n_recordings):.0f}",
            "n_excluded": f"{self.n_recordings - self.n_usable:,}",
            "n_detections": f"{self.n_detections:,}",
            "n_confident": f"{self.n_confident:,}",
            "n_both": f"{self.n_both:,}",
            "n_species": self.n_species,
        }


def summarize(conn) -> Summary:
    recordings = conn.execute(
        """
        SELECT count(*), count(DISTINCT site_code),
               min(recorded_at_local)::date, max(recorded_at_local)::date,
               count(*) FILTER (WHERE is_usable)
        FROM staging.stg_audio_features
        """
    ).fetchone()
    detections = conn.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE is_confident),
               count(*) FILTER (WHERE is_confident AND is_expected_here),
               count(DISTINCT scientific_name)
                   FILTER (WHERE is_confident AND is_expected_here)
        FROM staging.stg_bird_detections
        """
    ).fetchone()
    return Summary(*recordings, *detections)


def export(settings: Settings, out_dir: Path) -> dict[str, dict[str, int]]:
    """Write both folders; returns the rows of every table."""
    counts = {}
    with pg_connect(settings) as conn:
        values = summarize(conn).values()
        for folder_name, tables in queries(settings.features_n_mfcc).items():
            folder = out_dir / folder_name
            if folder.exists():
                shutil.rmtree(folder)  # a release is rebuilt whole, never patched
            folder.mkdir(parents=True)
            rows = {}
            for file_name, query in tables.items():
                cursor = conn.execute(query)
                columns = [column.name for column in cursor.description]
                rows[file_name] = write_csv(folder / file_name, columns, cursor)
                log.info("%s/%s: %d rows", folder_name, file_name, rows[file_name])
            for file_name in DOC_TABLES.get(folder_name, []):
                shutil.copyfile(DOCS / file_name, folder / file_name)
                with (folder / file_name).open(encoding="utf-8") as file:
                    rows[file_name] = sum(1 for _ in file) - 1
            readme = render(
                DOCS / "release" / f"{folder_name}.md",
                values | {"files": file_table(folder, rows)},
            )
            (folder / "README.md").write_text(readme, encoding="utf-8")
            name, url = LICENCES[folder_name]
            (folder / "LICENSE.txt").write_text(
                f"The data files in this folder are licensed under the\n"
                f"{name}.\nFull text: {url}\n\nAttribution: see README.md.\n",
                encoding="utf-8",
            )
            write_checksums(folder)
            zip_folder(folder, out_dir / f"soundscape-{folder_name}-v{VERSION}.zip")
            counts[folder_name] = rows
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/release")
    counts = export(Settings(), out_dir)
    log.info("Release %s written to %s: %s", VERSION, out_dir, counts)


if __name__ == "__main__":
    main()
