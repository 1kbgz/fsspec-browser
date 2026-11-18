import json

import fsspec
import pytest

from fsspec_browser import sources
from fsspec_browser.tests.test_web import _catalog_fs


def test_terminal_pages_tables_metadata_and_files():
    fs = _catalog_fs()

    def page(path, offset):
        result = sources.terminal_page(fs, path, offset, 2, None)
        assert result is not None
        return json.loads(result[0]), result[1]

    assert page("/orders", 0) == ([{"id": 0}, {"id": 1}], True)
    assert page("/orders", 4) == ([{"id": 4}], False)
    metadata, more = page("/orders/id", 0)
    assert metadata["arrow_type"] == "int64" and more is False

    assert sources.terminal_page(fs, "/notes.txt", 0, 2, None) is None
    with pytest.raises(IsADirectoryError):
        sources.terminal_page(fs, "/folder", 0, 2, None)


def test_table_pages_pass_row_offsets_to_the_source():
    fs = _catalog_fs()
    calls = []
    scan_selected = fs.scan_selected

    def recording(path, **options):
        calls.append(options)
        return scan_selected(path, **options)

    fs.scan_selected = recording

    assert sources.table_rows(fs, "/orders", 3, 2, None) == [{"id": 3}, {"id": 4}]
    assert calls == [{"row_offset": 3, "batch_size": 2, "row_limit": 2, "byte_limit": None}]


def test_terminal_previews_follow_facets_or_file_types(tmp_path):
    fs = _catalog_fs()
    assert sources.terminal_previewable(fs, "/orders", True) is True
    assert sources.terminal_previewable(fs, "/folder", True) is False
    assert sources.terminal_previewable(fs, "/orders/id", False) is True

    local = fsspec.filesystem("file")
    (tmp_path / "a.csv").write_text("x\n1\n")
    assert sources.terminal_previewable(local, str(tmp_path / "a.csv"), False) is True
    assert sources.terminal_previewable(local, str(tmp_path), True) is False
    assert sources.terminal_page(local, str(tmp_path / "a.csv"), 0, 2, None) is None


def test_kafka_partitions_page_by_offset():
    class Kafka:
        protocol = ("kafka+offset", "kafka")

    partition = {"name": "orders/0", "type": "directory", "kind": "partition"}
    assert sources.is_kafka_partition(Kafka(), partition) is True
    assert sources.is_kafka_partition(Kafka(), {**partition, "kind": "topic"}) is False
    assert sources.is_kafka_partition(object(), partition) is False


def test_files_without_facets_preview_as_bytes():
    from fsspec_data import DataSource, Node

    class Opaque(DataSource):
        def info(self, path):
            return {"name": path, "type": "file", "size": 1}

        def describe(self, path):
            return Node(path, [])

    assert sources.terminal_page(Opaque(), "blob", 0, 2, None) is None
    assert sources.terminal_previewable(Opaque(), "blob", False) is False
