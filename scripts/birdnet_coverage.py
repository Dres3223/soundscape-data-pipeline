"""BirdNET's coverage of the dataset's birds, and its speed on a sample.

Matches the 146 birds of the BirdCLEF 2025 taxonomy with BirdNET V2.4's
classes (by scientific name, then by common name), takes each one's highest
geographic score at the reserve over the weeks of the recordings, and times
BirdNET on two batches of 100 recordings (the pipeline's BATCH_SIZE).
Writes the species table as CSV and prints a summary.
See docs/detections_schema.md for the results.

Usage (from the project root):
    uv run python scripts/birdnet_coverage.py \\
        data/raw/birdclef docs/detections_coverage.csv
"""

import csv
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import birdnet

from soundscape.detections import LATITUDE, LONGITUDE, MODEL_VERSION, birdnet_week

SAMPLE_BATCHES = 2


def recorded_at(path: Path) -> datetime:
    _, day, clock = path.stem.split("_")
    return datetime.strptime(f"{day}_{clock}", "%Y%m%d_%H%M%S")


def highest_geo_scores(weeks: list[int]) -> dict[str, float]:
    model = birdnet.load("geo", MODEL_VERSION, "tf", library="litert")
    best: dict[str, float] = {}
    for week in weeks:
        table = model.predict(LATITUDE, LONGITUDE, week=week, min_confidence=0.0)
        frame = table.to_dataframe()
        for label, score in zip(
            frame["species_name"], frame["confidence"], strict=True
        ):
            best[label] = max(best.get(label, 0.0), float(score))
    return best


def coverage(taxonomy: Path, labels: list[str], geo: dict[str, float]) -> list[dict]:
    by_scientific = {label.split("_", 1)[0]: label for label in labels}
    by_common = {label.split("_", 1)[1].lower(): label for label in labels}
    rows = []
    with open(taxonomy) as f:
        for row in csv.DictReader(f):
            if row["class_name"] != "Aves":
                continue
            label = by_scientific.get(row["scientific_name"])
            match = "scientific name" if label else "not covered"
            if not label and row["common_name"].lower() in by_common:
                label = by_common[row["common_name"].lower()]
                match = "common name"
            score = geo.get(label) if label else None
            rows.append(
                {
                    "primary_label": row["primary_label"],
                    "scientific_name": row["scientific_name"],
                    "common_name": row["common_name"],
                    "birdnet_label": label or "",
                    "match": match,
                    "geo_score_max": "" if score is None else round(score, 4),
                }
            )
    return rows


def seconds_per_recording(model, files: list[Path], batch_size: int) -> list[float]:
    random.seed(38)
    sample = random.sample(files, batch_size * SAMPLE_BATCHES)
    times = []
    for start in range(0, len(sample), batch_size):
        began = time.perf_counter()
        model.predict(
            sample[start : start + batch_size],
            top_k=None,
            default_confidence_threshold=0.1,
        ).to_dataframe()
        times.append((time.perf_counter() - began) / batch_size)
    return times


def main() -> None:
    data, output = Path(sys.argv[1]), Path(sys.argv[2])
    files = sorted((data / "train_soundscapes").glob("*.ogg"))
    weeks = sorted({birdnet_week(recorded_at(path)) for path in files})

    acoustic = birdnet.load("acoustic", MODEL_VERSION, "tf", library="litert")
    rows = coverage(
        data / "taxonomy.csv", list(acoustic.species_list), highest_geo_scores(weeks)
    )
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    times = seconds_per_recording(acoustic, files, batch_size=100)
    covered = [row for row in rows if row["birdnet_label"]]
    summary = {
        "birds": len(rows),
        "covered": len(covered),
        "not_covered": [
            row["scientific_name"] for row in rows if not row["birdnet_label"]
        ],
        "weeks": weeks,
        "below_geo_0.03": [
            row["scientific_name"]
            for row in covered
            if (row["geo_score_max"] or 0) < 0.03
        ],
        "seconds_per_recording": [round(t, 3) for t in times],
    }
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
