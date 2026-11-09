from datetime import datetime

import pytest
from botocore.exceptions import ClientError

from soundscape.ingest import (
    RecordingName,
    build_s3_key,
    ensure_bucket,
    parse_file_name,
)


@pytest.mark.parametrize(
    ("file_name", "site_code", "recorded_at"),
    [
        ("H02_20230422_014500.ogg", "H02", datetime(2023, 4, 22, 1, 45, 0)),
        # Irregular site codes found in the dataset
        ("O201_20230512_011500.ogg", "O201", datetime(2023, 5, 12, 1, 15, 0)),
        ("H8749_20230427_084000.ogg", "H8749", datetime(2023, 4, 27, 8, 40, 0)),
    ],
)
def test_parse_file_name_valid(file_name, site_code, recorded_at):
    assert parse_file_name(file_name) == RecordingName(site_code, recorded_at)


@pytest.mark.parametrize(
    "file_name",
    [
        "H02_20230422_014500.wav",  # wrong extension
        "h02_20230422_014500.ogg",  # lowercase site
        "H02_2023042_014500.ogg",  # short date
        "H02-20230422-014500.ogg",  # wrong separator
        "H02_20230231_014500.ogg",  # 31 February does not exist
        "H02_20230422_256000.ogg",  # hour 25 does not exist
    ],
)
def test_parse_file_name_invalid(file_name):
    with pytest.raises(ValueError):
        parse_file_name(file_name)


def test_build_s3_key_is_hive_partitioned():
    name = RecordingName("H02", datetime(2023, 4, 22, 1, 45, 0))
    key = build_s3_key("birdclef-2025", name, "H02_20230422_014500.ogg")
    expected = "raw/birdclef-2025/site=H02/date=2023-04-22/H02_20230422_014500.ogg"
    assert key == expected


class BucketS3:
    """A client whose head_bucket answers with the given HTTP status."""

    def __init__(self, status: int):
        self.status = status
        self.created = []

    def head_bucket(self, Bucket):  # noqa: N803 (boto3's argument name)
        if self.status != 200:
            response = {"ResponseMetadata": {"HTTPStatusCode": self.status}}
            raise ClientError(response, "HeadBucket")

    def create_bucket(self, Bucket):  # noqa: N803
        self.created.append(Bucket)


@pytest.mark.parametrize(
    ("status", "created"),
    [(200, []), (404, ["b"]), (403, [])],  # 403: managed elsewhere, leave it
)
def test_ensure_bucket_creates_it_only_when_missing(status, created):
    s3 = BucketS3(status)

    ensure_bucket(s3, "b")

    assert s3.created == created


def test_ensure_bucket_reports_other_errors():
    with pytest.raises(ClientError):
        ensure_bucket(BucketS3(500), "b")
