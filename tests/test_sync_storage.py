import io

from soundscape.sync_storage import objects_to_copy, sync


class FakeS3:
    """Just enough of the boto3 client to copy objects in memory."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = objects or {}

    def get_paginator(self, _operation):
        return self

    def paginate(self, Bucket):  # noqa: N803 (boto3's argument name)
        items = [{"Key": k, "Size": len(v)} for k, v in self.objects.items()]
        # Two pages, like S3 does past 1,000 keys
        yield {"Contents": items[:1]}
        yield {"Contents": items[1:]}

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.objects[Key] = Body


def test_objects_to_copy_picks_missing_and_different_sizes():
    source = {"same": 1, "missing": 2, "changed": 3}
    target = {"same": 1, "changed": 9, "only-in-target": 4}

    assert objects_to_copy(source, target) == ["changed", "missing"]


def test_sync_copies_with_the_same_paths_and_can_be_repeated():
    source = FakeS3({"raw/a.ogg": b"aa", "features/b.parquet": b"bbb"})
    target = FakeS3()

    first = sync(source, "from", target, "to")
    second = sync(source, "from", target, "to")

    assert target.objects == source.objects
    assert first == {"copied": 2, "skipped": 0}
    assert second == {"copied": 0, "skipped": 2}
