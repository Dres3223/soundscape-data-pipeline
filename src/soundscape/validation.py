"""Compare BirdNET's detections with the published labels of El Silencio.

Usage:
    uv run python -m soundscape.validation [work folder] [output folder]

El Silencio Multi-Taxonomic (Zenodo, doi:10.5281/zenodo.17064353, CC BY 4.0)
has 770 one-minute WAV recordings from 7 sites and boxes in time and frequency
for the calls heard in them. This module runs BirdNET on them with the
pipeline's settings, one site at a time (download, analyze, delete the audio),
and measures how often its detections agree with the labels:

- per 3-second segment: is a species labeled in the segment where BirdNET
  detects it?
- per recording: is a species BirdNET detects in a minute labeled anywhere in
  that minute? This is the level of marts.mart_species_by_site_period.

The labels are taken as the truth, although the dataset does not say who made
them. Results and limits: docs/validation.md.
"""

import csv
import json
import logging
import math
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from soundscape.detections import birdnet_week, detect, geo_scores, split_species

log = logging.getLogger("soundscape.validation")

ZENODO = "https://zenodo.org/records/17064353/files/{name}?download=1"
SITES = ("H23", "H64", "H75", "H80", "H82", "H87", "H96")
LABEL_FILES = ("strong_labels.csv", "taxonomy_dict.csv")

SEGMENT_S = 3.0
SEGMENTS = 20  # one minute
# Label names that differ from BirdNET's (eBird 2021) taxonomy
NAME_FIXES = {
    "Baryptengus martii": "Baryphthengus martii",  # misspelt
    "Phyllomyias griceiceps": "Phyllomyias griseiceps",  # misspelt
    "Zimerius chrysops": "Zimmerius chrysops",  # misspelt
    "Saltator olivaceus": "Saltator olivascens",  # Olivaceous Saltator
    # Split by eBird; the Magdalena valley population is S. stenorhyncha
    "Schiffornis turdinus": "Schiffornis stenorhyncha",
}
CONFIDENCE_THRESHOLDS = tuple(round(0.1 + 0.05 * i, 2) for i in range(18))  # to 0.95
GEO_THRESHOLDS = (0.0, 0.02, 0.03)
BOOTSTRAP_SAMPLES = 1000

# (file name, species, labeled, highest BirdNET score, geographic score)
Row = tuple[str, str, bool, float, float | None]


def is_species(identification: str) -> bool:
    """Whether a label names a species, not a sonotype or an unknown sound."""
    return not (
        "_SON" in identification
        or identification.startswith("Unidentified")
        or identification.upper() == "UNKNOWN"
    )


def is_bird_class(label: str) -> bool:
    """BirdNET's non-bird classes repeat their name ('Engine_Engine')."""
    scientific, common = split_species(label)
    return scientific != common


def segments_overlapping(begin_s: float, end_s: float) -> range:
    first = max(0, math.floor(begin_s / SEGMENT_S))
    last = min(SEGMENTS - 1, math.ceil(end_s / SEGMENT_S) - 1)
    return range(first, last + 1)


def read_labels(strong_labels: Path, taxonomy: Path) -> dict:
    """Labeled species per segment, segments with unidentified birds, files."""
    with open(taxonomy) as f:
        names = {row["Label"]: row["Identification"] for row in csv.DictReader(f)}
    species = set()
    unidentified = set()
    files = set()
    with open(strong_labels) as f:
        for row in csv.DictReader(f):
            files.add(row["file_name"])
            if row["group"] != "AVE":
                continue
            name = names.get(row["label"], row["label"])
            name = NAME_FIXES.get(name, name)
            segments = segments_overlapping(
                float(row["begin_time_s"]), float(row["end_time_s"])
            )
            for segment in segments:
                if is_species(name):
                    species.add((row["file_name"], segment, name))
                else:
                    unidentified.add((row["file_name"], segment))
    return {"species": species, "unidentified": unidentified, "files": files}


def recording_week(file_name: str) -> int:
    _, day, _ = Path(file_name).stem.split("_")
    return birdnet_week(datetime.strptime(day, "%Y%m%d"))


def segment_rows(
    labels: dict,
    detections: list[dict],
    geo: dict[int, dict[str, float]],
) -> list[Row]:
    """One row per segment and species that is labeled or detected.

    A detection in a segment with an unidentified bird and no label for that
    species is left out: it may be right, so it is neither a hit nor an error.
    """
    scores: dict[tuple[str, int, str], float] = {}
    for detection in detections:
        if detection["file_name"] not in labels["files"]:
            continue
        if not is_bird_class(detection["label"]):
            continue
        scientific, _ = split_species(detection["label"])
        key = (
            detection["file_name"],
            round(detection["start_s"] / SEGMENT_S),
            scientific,
        )
        scores[key] = max(scores.get(key, 0.0), detection["confidence"])

    geo_by_name = {
        week: {split_species(label)[0]: score for label, score in by_label.items()}
        for week, by_label in geo.items()
    }
    rows = []
    for key in labels["species"] | scores.keys():
        file_name, segment, species = key
        labeled = key in labels["species"]
        if not labeled and (file_name, segment) in labels["unidentified"]:
            continue
        week_scores = geo_by_name.get(recording_week(file_name), {})
        rows.append(
            (
                file_name,
                species,
                labeled,
                scores.get(key, 0.0),
                week_scores.get(species),
            )
        )
    return rows


def recording_rows(rows: list[Row]) -> list[Row]:
    """The same rows, per recording and species."""
    merged: dict[tuple[str, str], list] = {}
    for file_name, species, labeled, score, geo in rows:
        row = merged.setdefault((file_name, species), [False, 0.0, geo])
        row[0] = row[0] or labeled
        row[1] = max(row[1], score)
    return [
        (file_name, species, labeled, score, geo)
        for (file_name, species), (labeled, score, geo) in merged.items()
    ]


def is_predicted(row: Row, confidence: float, geo_min: float) -> bool:
    _, _, _, score, geo = row
    passes_geo = geo_min == 0 or (geo is not None and geo >= geo_min)
    return score >= confidence and passes_geo


def rates(tp: float, fp: float, fn: float) -> dict[str, float | None]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def counts_per_file(
    rows: list[Row], confidence: float, geo_min: float
) -> dict[str, list[int]]:
    """True positives, false positives and false negatives per recording."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        predicted = is_predicted(row, confidence, geo_min)
        labeled = row[2]
        if predicted and labeled:
            counts[row[0]][0] += 1
        elif predicted:
            counts[row[0]][1] += 1
        elif labeled:
            counts[row[0]][2] += 1
    return counts


def evaluate(
    rows: list[Row],
    files: set[str],
    confidence: float,
    geo_min: float,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = 39,
) -> dict:
    """Precision, recall and F1, with 95 % intervals resampling recordings."""
    counts = counts_per_file(rows, confidence, geo_min)
    table = np.array([counts.get(name, [0, 0, 0]) for name in sorted(files)])
    tp, fp, fn = (int(value) for value in table.sum(axis=0))
    result = {"tp": tp, "fp": fp, "fn": fn, **rates(tp, fp, fn)}
    if samples:
        rng = np.random.default_rng(seed)
        picks = rng.integers(0, len(table), size=(samples, len(table)))
        sums = table[picks].sum(axis=1)
        draws = [rates(*sample) for sample in sums]
        for metric in ("precision", "recall", "f1"):
            values = [draw[metric] for draw in draws if draw[metric] is not None]
            low, high = np.percentile(values, [2.5, 97.5]) if values else (None, None)
            result[f"{metric}_low"], result[f"{metric}_high"] = low, high
    return result


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """95 % interval for a proportion; sound with few cases, unlike p ± 2·se."""
    if not total:
        return None
    p = successes / total
    centre = (p + z**2 / (2 * total)) / (1 + z**2 / total)
    half = (
        z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / (1 + z**2 / total)
    )
    return centre - half, centre + half


def per_species(rows: list[Row], confidence: float, geo_min: float) -> list[dict]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        predicted = is_predicted(row, confidence, geo_min)
        labeled = row[2]
        index = (
            0 if predicted and labeled else 1 if predicted else 2 if labeled else None
        )
        if index is not None:
            totals[row[1]][index] += 1
    table = []
    for species, (tp, fp, fn) in sorted(totals.items()):
        precision_ci = wilson(tp, tp + fp)
        recall_ci = wilson(tp, tp + fn)
        table.append(
            {
                "species": species,
                "labeled": tp + fn,
                "detected": tp + fp,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                **rates(tp, fp, fn),
                "precision_low": precision_ci and precision_ci[0],
                "precision_high": precision_ci and precision_ci[1],
                "recall_low": recall_ci and recall_ci[0],
                "recall_high": recall_ci and recall_ci[1],
            }
        )
    return table


def download(name: str, target: Path) -> None:
    """Download with curl, retrying: the connection to Zenodo is unreliable."""
    subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry",
            "8",
            "--retry-all-errors",
            "--output",
            str(target),
            ZENODO.format(name=name),
        ],
        check=True,
    )


def extract_wavs(archive: Path, folder: Path) -> list[Path]:
    """Extract only the WAV files, by base name (never paths from the zip).

    The Zenodo zips also hold macOS metadata ('__MACOSX/', '._<name>.WAV'),
    which is not audio.
    """
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            name = Path(member.filename).name
            if (
                member.is_dir()
                or not name.upper().endswith(".WAV")
                or name.startswith("._")
                or member.filename.startswith("__MACOSX/")
            ):
                continue
            path = folder / name
            with zipped.open(member) as source, open(path, "wb") as target:
                shutil.copyfileobj(source, target)
            paths.append(path)
    return sorted(paths)


def analyze_site(site: str, work: Path) -> Path:
    """BirdNET detections of one site as CSV; the audio is deleted after."""
    output = work / f"detections_{site}.csv"
    if output.exists():
        log.info("%s already analyzed", site)
        return output
    archive = work / f"{site}.zip"
    log.info("Downloading %s", archive.name)
    download(archive.name, archive)
    audio = work / site
    try:
        paths = extract_wavs(archive, audio)
        archive.unlink()
        log.info("%s: %d recordings, running BirdNET", site, len(paths))
        found, failed = detect(paths)
        if failed:
            log.warning("%s: BirdNET could not read %s", site, sorted(failed))
        partial = output.with_suffix(".partial")
        with open(partial, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["file_name", "start_s", "label", "confidence"])
            for file_name, rows in sorted(found.items()):
                for row in rows:
                    writer.writerow(
                        [file_name, row["start_s"], row["label"], row["confidence"]]
                    )
        partial.rename(output)
    finally:
        shutil.rmtree(audio, ignore_errors=True)
        archive.unlink(missing_ok=True)
    return output


def read_detections(paths: list[Path]) -> list[dict]:
    detections = []
    for path in paths:
        with open(path) as f:
            for row in csv.DictReader(f):
                detections.append(
                    {
                        "file_name": row["file_name"],
                        "start_s": float(row["start_s"]),
                        "label": row["label"],
                        "confidence": float(row["confidence"]),
                    }
                )
    return detections


def write_csv(path: Path, rows: list[dict]) -> None:
    def clean(value):
        return (
            round(float(value), 4) if isinstance(value, float | np.floating) else value
        )

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(
            {key: clean(value) for key, value in row.items()} for row in rows
        )


def run(work: Path, output: Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    for name in LABEL_FILES:
        if not (work / name).exists():
            download(name, work / name)
    labels = read_labels(work / "strong_labels.csv", work / "taxonomy_dict.csv")
    detections = read_detections([analyze_site(site, work) for site in SITES])
    weeks = {recording_week(name) for name in labels["files"]}
    segments = segment_rows(labels, detections, geo_scores(weeks))
    levels = {"segment": segments, "recording": recording_rows(segments)}
    labeled = {species for _, _, species in labels["species"]}

    curve = []
    for level, all_rows in levels.items():
        # "labeled": only species found somewhere in the labels, in case the
        # annotators left some birds out (a sensitivity check, not the result)
        for species_set in ("all", "labeled"):
            rows = all_rows
            if species_set == "labeled":
                rows = [row for row in all_rows if row[1] in labeled]
            for geo_min in GEO_THRESHOLDS:
                for confidence in CONFIDENCE_THRESHOLDS:
                    curve.append(
                        {
                            "level": level,
                            "species_set": species_set,
                            "geo_min": geo_min,
                            "confidence": confidence,
                            **evaluate(rows, labels["files"], confidence, geo_min),
                        }
                    )
    write_csv(output / "validation_curve.csv", curve)

    by_recording = [
        row
        for row in curve
        if row["level"] == "recording" and row["species_set"] == "all"
    ]
    best = max(by_recording, key=lambda row: row["f1"])
    species_table = []
    for confidence in sorted({best["confidence"], 0.5}):
        for row in per_species(levels["recording"], confidence, best["geo_min"]):
            species_table.append(
                {"confidence": confidence, "geo_min": best["geo_min"], **row}
            )
    write_csv(output / "validation_species.csv", species_table)
    summary = {
        "recordings": len(labels["files"]),
        "labeled_species": len(labeled),
        "best_by_recording_f1": {
            "confidence": best["confidence"],
            "geo_min": best["geo_min"],
        },
    }
    log.info("%s", json.dumps(summary))
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/validation")
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs")
    run(work, output)


if __name__ == "__main__":
    main()
