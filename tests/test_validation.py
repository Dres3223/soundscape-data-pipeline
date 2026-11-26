import csv
import io
import zipfile

import pytest

from soundscape import validation
from soundscape.validation import (
    evaluate,
    extract_wavs,
    is_bird_class,
    is_species,
    per_species,
    read_labels,
    recording_rows,
    recording_week,
    segment_rows,
    segments_overlapping,
    wilson,
)

FILE = "H23_20230423_171500.WAV"  # week 16
OTHER = "H64_20230501_060000.WAV"  # week 17


def write(path, header, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def labels_from(tmp_path, boxes):
    """boxes: (file, group, code, begin_s, end_s)."""
    header = ["file_name", "group", "label", "begin_time_s", "end_time_s"]
    strong = write(tmp_path / "strong.csv", header, boxes)
    taxonomy = write(
        tmp_path / "taxonomy.csv",
        ["Label", "Group", "Identification"],
        [
            ["LEPVER", "AVE", "Leptotila verreauxi"],
            ["BARMAR", "AVE", "Baryptengus martii"],
            ["SON019", "AVE", "AVE_SON019"],
            ["BOAPUG", "ANU", "Boana pugnax"],
        ],
    )
    return read_labels(strong, taxonomy)


def detection(file_name, start_s, label, confidence):
    return {
        "file_name": file_name,
        "start_s": start_s,
        "label": label,
        "confidence": confidence,
    }


DOVE = "Leptotila verreauxi_White-tipped Dove"
MOTMOT = "Baryphthengus martii_Rufous Motmot"
GEO = {16: {DOVE: 0.5, MOTMOT: 0.01}, 17: {DOVE: 0.5, MOTMOT: 0.01}}


def test_segments_overlapping_a_box():
    assert list(segments_overlapping(0.0, 0.8)) == [0]
    assert list(segments_overlapping(2.5, 3.5)) == [0, 1]
    assert list(segments_overlapping(3.0, 6.0)) == [1]
    assert list(segments_overlapping(58.0, 61.0)) == [19]


def test_species_and_bird_classes():
    assert is_species("Leptotila verreauxi")
    assert not is_species("AVE_SON019")
    assert not is_species("Unidentified AVE Sound")
    assert not is_species("UNKNOWN")
    assert is_bird_class(DOVE)
    assert not is_bird_class("Engine_Engine")


def test_recording_week_comes_from_the_file_name():
    assert recording_week(FILE) == 16


def test_labels_keep_identified_birds_and_fix_names(tmp_path):
    labels = labels_from(
        tmp_path,
        [
            [FILE, "AVE", "BARMAR", 1.0, 4.0],
            [FILE, "AVE", "SON019", 10.0, 11.0],
            [FILE, "ANU", "BOAPUG", 20.0, 21.0],
            [OTHER, "ANU", "BOAPUG", 1.0, 2.0],
        ],
    )

    assert labels["species"] == {
        (FILE, 0, "Baryphthengus martii"),
        (FILE, 1, "Baryphthengus martii"),
    }
    assert labels["unidentified"] == {(FILE, 3)}
    # A recording with only frogs is annotated too: it has no birds
    assert labels["files"] == {FILE, OTHER}


def test_hits_errors_and_misses_per_segment_and_recording(tmp_path):
    labels = labels_from(
        tmp_path,
        [
            [FILE, "AVE", "LEPVER", 0.5, 1.0],  # segment 0
            [FILE, "AVE", "LEPVER", 30.5, 31.0],  # segment 10, missed
            [FILE, "AVE", "SON019", 12.5, 13.0],  # segment 4, unidentified
            [OTHER, "ANU", "BOAPUG", 1.0, 2.0],
        ],
    )
    detections = [
        detection(FILE, 0.0, DOVE, 0.9),  # hit
        detection(FILE, 6.0, DOVE, 0.8),  # wrong segment
        detection(FILE, 12.0, MOTMOT, 0.7),  # where an unknown bird sings: ignored
        detection(FILE, 15.0, "Engine_Engine", 0.9),  # not a bird
        detection(OTHER, 0.0, MOTMOT, 0.6),  # no bird labeled there
        detection("H99_20230423_000000.WAV", 0.0, DOVE, 0.9),  # not annotated
    ]

    segments = segment_rows(labels, detections, GEO)
    files = labels["files"]

    by_segment = evaluate(segments, files, 0.5, 0.0, samples=0)
    assert (by_segment["tp"], by_segment["fp"], by_segment["fn"]) == (1, 2, 1)

    by_recording = evaluate(recording_rows(segments), files, 0.5, 0.0, samples=0)
    # The dove is labeled and detected in FILE; the motmot is an error in OTHER
    assert (by_recording["tp"], by_recording["fp"], by_recording["fn"]) == (1, 1, 0)
    assert by_recording["precision"] == 0.5
    assert by_recording["recall"] == 1.0


def test_thresholds_trade_errors_for_misses(tmp_path):
    labels = labels_from(tmp_path, [[FILE, "AVE", "LEPVER", 0.5, 1.0]])
    detections = [detection(FILE, 0.0, DOVE, 0.6), detection(FILE, 3.0, MOTMOT, 0.9)]
    rows = recording_rows(segment_rows(labels, detections, GEO))
    files = labels["files"]

    # High confidence keeps the wrong motmot and loses the dove
    high = evaluate(rows, files, 0.7, 0.0, samples=0)
    assert (high["tp"], high["fp"], high["fn"]) == (0, 1, 1)
    # The geographic filter drops the motmot (0.01), not the dove (0.5)
    filtered = evaluate(rows, files, 0.5, 0.03, samples=0)
    assert (filtered["tp"], filtered["fp"], filtered["fn"]) == (1, 0, 0)


def test_bootstrap_interval_contains_the_estimate(tmp_path):
    boxes = [
        [f"H23_202304{day:02d}_060000.WAV", "AVE", "LEPVER", 0.5, 1.0]
        for day in range(1, 21)
    ]
    labels = labels_from(tmp_path, boxes)
    # Detected in half of the recordings
    detections = [detection(box[0], 0.0, DOVE, 0.9) for box in boxes[::2]]
    rows = recording_rows(segment_rows(labels, detections, GEO))

    result = evaluate(rows, labels["files"], 0.5, 0.0, samples=200)

    assert result["recall"] == 0.5
    assert result["recall_low"] < 0.5 < result["recall_high"]
    assert result["precision_low"] == result["precision_high"] == 1.0


def test_wilson_interval():
    low, high = wilson(5, 10)
    assert low == pytest.approx(0.237, abs=0.001)
    assert high == pytest.approx(0.763, abs=0.001)
    assert wilson(0, 0) is None


def test_per_species_counts(tmp_path):
    labels = labels_from(tmp_path, [[FILE, "AVE", "LEPVER", 0.5, 1.0]])
    detections = [detection(FILE, 3.0, MOTMOT, 0.9)]
    rows = recording_rows(segment_rows(labels, detections, GEO))

    table = {row["species"]: row for row in per_species(rows, 0.5, 0.0)}

    assert table["Leptotila verreauxi"]["fn"] == 1
    assert table["Leptotila verreauxi"]["recall"] == 0.0
    assert table["Baryphthengus martii"]["fp"] == 1
    assert table["Baryphthengus martii"]["precision"] == 0.0


def test_extract_wavs_ignores_paths_other_files_and_mac_metadata(tmp_path):
    archive = tmp_path / "H23.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr("H23/H23_20230423_171500.WAV", b"audio")
        zipped.writestr("../../escape.WAV", b"audio")
        zipped.writestr("H23/readme.txt", b"text")
        zipped.writestr("H23/._H23_20230423_171500.WAV", b"mac")
        zipped.writestr("__MACOSX/H23/H23_20230423_171500.WAV", b"mac")
    archive.write_bytes(buffer.getvalue())

    paths = extract_wavs(archive, tmp_path / "out")

    assert [path.name for path in paths] == ["H23_20230423_171500.WAV", "escape.WAV"]
    assert all(path.parent == tmp_path / "out" for path in paths)
    assert paths[0].read_bytes() == b"audio"  # not the macOS copy


def test_run_writes_the_curve_and_the_species_table(tmp_path, monkeypatch):
    work, output = tmp_path / "work", tmp_path / "out"
    work.mkdir()
    write(
        work / "strong_labels.csv",
        ["file_name", "group", "label", "begin_time_s", "end_time_s"],
        [[FILE, "AVE", "LEPVER", 0.5, 1.0], [OTHER, "ANU", "BOAPUG", 1.0, 2.0]],
    )
    write(
        work / "taxonomy_dict.csv",
        ["Label", "Group", "Identification"],
        [["LEPVER", "AVE", "Leptotila verreauxi"], ["BOAPUG", "ANU", "Boana pugnax"]],
    )

    def analyze_site(site, work):
        path = work / f"detections_{site}.csv"
        rows = [[FILE, 0.0, DOVE, 0.9]] if site == "H23" else []
        return write(path, ["file_name", "start_s", "label", "confidence"], rows)

    monkeypatch.setattr(validation, "analyze_site", analyze_site)
    monkeypatch.setattr(validation, "geo_scores", lambda weeks: GEO)

    summary = validation.run(work, output)

    assert summary["recordings"] == 2
    assert summary["labeled_species"] == 1
    with open(output / "validation_curve.csv") as f:
        curve = list(csv.DictReader(f))
    # 2 levels x 2 species sets x 3 geographic x 18 confidence thresholds
    assert len(curve) == 2 * 2 * 3 * 18
    with open(output / "validation_species.csv") as f:
        species = list(csv.DictReader(f))
    assert {row["species"] for row in species} == {"Leptotila verreauxi"}
    assert all(row["tp"] == "1" for row in species)
