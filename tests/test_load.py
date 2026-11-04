import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from soundscape.features import FEATURES_SCHEMA
from soundscape.load import list_feature_keys, read_features


class FakeS3:
    """Just enough of the boto3 client to read files from memory."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_paginator(self, _operation):
        return self

    def paginate(self, Bucket, Prefix):  # noqa: N803 (boto3's argument names)
        keys = [key for key in self.objects if key.startswith(Prefix)]
        # Two pages, like S3 does past 1,000 keys
        yield {"Contents": [{"Key": key} for key in keys[:1]]}
        yield {"Contents": [{"Key": key} for key in keys[1:]]}

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}


def parquet(table: pa.Table) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def test_list_feature_keys_reads_every_page_and_only_parquet():
    s3 = FakeS3(
        {
            "features/site=H02/month=2023-04/features.parquet": b"",
            "features/site=O201/month=2023-05/features.parquet": b"",
            "features/notes.txt": b"",
            "raw/H02.ogg": b"",
        }
    )

    assert list_feature_keys(s3, "bucket") == [
        "features/site=H02/month=2023-04/features.parquet",
        "features/site=O201/month=2023-05/features.parquet",
    ]


def test_read_features_with_no_files_gives_an_empty_table():
    table = read_features(FakeS3({}), "bucket", [])

    assert table.num_rows == 0
    assert table.schema == FEATURES_SCHEMA


def test_read_features_rejects_a_different_schema():
    other = pa.table({"sha256": ["0" * 64], "something_else": [1.0]})
    s3 = FakeS3({"features/bad.parquet": parquet(other)})

    with pytest.raises(ValueError, match="does not match FEATURES_SCHEMA"):
        read_features(s3, "bucket", ["features/bad.parquet"])
