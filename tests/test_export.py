import hashlib
import subprocess
import zipfile
from datetime import date, datetime

import pytest

from soundscape.export import (
    DOCS,
    cell,
    file_table,
    mfcc_columns,
    queries,
    render,
    write_checksums,
    write_csv,
    zip_folder,
)


def test_cells_are_written_the_same_way_everywhere():
    assert cell(None) == ""
    assert cell(True) == "true"
    assert cell(False) == "false"
    assert cell(0.30000001192092896) == "0.3"  # float32 stored as double
    assert cell(60.0) == "60"
    assert cell(-42.5) == "-42.5"
    assert cell(float("nan")) == ""
    assert cell(7) == "7"
    assert cell(datetime(2023, 4, 19, 5, 30)) == "2023-04-19 05:30:00"
    assert cell(date(2023, 4, 19)) == "2023-04-19"
    assert cell("Engine") == "Engine"


def test_one_column_per_mfcc_coefficient():
    columns = mfcc_columns(2)

    assert columns == [
        "mfcc_mean[1] AS mfcc_mean_01",
        "mfcc_mean[2] AS mfcc_mean_02",
        "mfcc_std[1] AS mfcc_std_01",
        "mfcc_std[2] AS mfcc_std_02",
    ]
    acoustic = queries(20)["indices"]["acoustic_indices.csv"]
    assert "mfcc_std[20] AS mfcc_std_20" in acoustic


def test_every_table_is_sorted_so_releases_are_reproducible():
    for tables in queries(20).values():
        for name, query in tables.items():
            assert "ORDER BY" in query, name


def test_csv_has_header_and_counts_rows(tmp_path):
    path = tmp_path / "t.csv"

    rows = write_csv(path, ["a", "b"], [(1, True), (None, 0.5)])

    assert rows == 2
    assert path.read_text() == "a,b\n1,true\n,0.5\n"


def test_checksums_follow_sha256sum_and_skip_themselves(tmp_path):
    (tmp_path / "b.csv").write_text("x\n")
    (tmp_path / "a.csv").write_text("y\n")
    write_checksums(tmp_path)
    write_checksums(tmp_path)  # running it again does not list SHA256SUMS

    lines = (tmp_path / "SHA256SUMS").read_text().splitlines()
    assert [line.split("  ")[1] for line in lines] == ["a.csv", "b.csv"]
    assert lines[0].split("  ")[0] == hashlib.sha256(b"y\n").hexdigest()
    check = subprocess.run(
        ["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=tmp_path, capture_output=True
    )
    assert check.returncode == 0


def test_file_table_lists_rows_and_sizes(tmp_path):
    (tmp_path / "a.csv").write_text("x" * 2048)

    table = file_table(tmp_path, {"a.csv": 1234})

    assert "| `a.csv` | 1,234 | 2 KB |" in table
    (tmp_path / "b.csv").write_text("x" * 128)
    assert "| `b.csv` | 2 | 128 bytes |" in file_table(tmp_path, {"b.csv": 2})


@pytest.mark.parametrize("name", ["indices", "detections"])
def test_readme_templates_need_every_value(name):
    template = DOCS / "release" / f"{name}.md"
    values = dict.fromkeys(
        [
            "version",
            "n_recordings",
            "n_sites",
            "first_date",
            "last_date",
            "n_usable",
            "share_usable",
            "n_excluded",
            "n_detections",
            "n_confident",
            "n_both",
            "n_species",
            "files",
        ],
        "X",
    )

    assert "$" not in render(template, values)
    with pytest.raises(KeyError):
        render(template, {"version": "1"})


def test_zip_is_the_same_for_the_same_files(tmp_path):
    folder = tmp_path / "indices"
    folder.mkdir()
    (folder / "b.csv").write_text("x\n")
    (folder / "a.csv").write_text("y\n")

    zip_folder(folder, tmp_path / "one.zip")
    (folder / "a.csv").touch()  # a new modification time changes nothing
    zip_folder(folder, tmp_path / "two.zip")

    assert (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()
    with zipfile.ZipFile(tmp_path / "one.zip") as archive:
        assert archive.namelist() == ["indices/a.csv", "indices/b.csv"]
        assert archive.read("indices/a.csv") == b"y\n"
