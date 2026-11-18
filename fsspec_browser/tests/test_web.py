import json
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest


def test_parse_args_accepts_terminal_storage_options():
    from fsspec_browser import web

    args = web._parse_args(
        [
            "s3://bucket/path",
            "-o",
            "endpoint_url=https://s3.us-east-005.backblazeb2.com",
            "-okey=value",
            "--storage-option",
            "secret=shh",
            "--storage-option=region=us-east-005",
            "--page-size",
            "0",
            "--preview-bytes",
            "0",
        ]
    )

    assert args.path == "s3://bucket/path"
    assert args.storage_options == {
        "endpoint_url": "https://s3.us-east-005.backblazeb2.com",
        "key": "value",
        "region": "us-east-005",
        "secret": "shh",
    }
    assert args.page_size == 1
    assert args.preview_bytes == 1


def test_parse_args_without_path_starts_without_session():
    from fsspec_browser import web

    args = web._parse_args([])

    assert args.path is None
    assert args.preview_bytes == 1 * 1024 * 1024


def test_default_static_assets_exist():
    from fsspec_browser import web

    static_dir = web._default_static_dir()

    assert (static_dir / "index.html").is_file()
    assert (static_dir / "cdn" / "index.js").is_file()
    assert (static_dir / "css" / "index.css").is_file()


def test_loopback_host_detection():
    from fsspec_browser import web

    assert web._is_loopback_host("127.0.0.1:8000") is True
    assert web._is_loopback_host("[::1]:8000") is True
    assert web._is_loopback_host("localhost") is True
    assert web._is_loopback_host("example.com") is False


def test_api_rejects_untrusted_host(tmp_path):
    from fsspec_browser import web

    server = web.create_server("127.0.0.1", 0, None, static_dir=tmp_path, download_root=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _host, port = server.server_address[:2]
        connection = HTTPConnection("127.0.0.1", port)
        connection.request(
            "POST",
            "/api/session",
            body=b"{}",
            headers={"content-type": "application/json", "host": "example.com"},
        )
        response = connection.getresponse()
        assert response.status == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_api_rejects_missing_token(tmp_path):
    from fsspec_browser import web

    server = web.create_server("127.0.0.1", 0, None, static_dir=tmp_path, download_root=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _host, port = server.server_address[:2]
        connection = HTTPConnection("127.0.0.1", port)
        connection.request("GET", "/api/config", headers={"host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        assert response.status == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_static_index_injects_token(tmp_path):
    from fsspec_browser import web

    (tmp_path / "index.html").write_text("<html><head></head><body></body></html>")
    server = web.create_server("127.0.0.1", 0, None, static_dir=tmp_path, download_root=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _host, port = server.server_address[:2]
        connection = HTTPConnection("127.0.0.1", port)
        connection.request("GET", "/", headers={"host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        body = response.read().decode()
        assert response.status == 200
        assert f'name="fsspec-browser-token" content="{server.token}"' in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_api_accepts_valid_token(tmp_path):
    from fsspec_browser import web

    server = web.create_server("127.0.0.1", 0, None, static_dir=tmp_path, download_root=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _host, port = server.server_address[:2]
        connection = HTTPConnection("127.0.0.1", port)
        connection.request(
            "GET",
            "/api/config",
            headers={
                "host": f"127.0.0.1:{port}",
                "x-fsspec-browser-token": server.token,
            },
        )
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"active": False}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_create_state_passes_storage_options(monkeypatch, tmp_path):
    from fsspec_browser import web

    calls = []

    class FakeFs:
        pass

    def fake_url_to_fs(url, **kwargs):
        calls.append((url, kwargs))
        return FakeFs(), "bucket/path"

    monkeypatch.setattr(web.fsspec.core, "url_to_fs", fake_url_to_fs)

    state = web.create_state(
        "s3://bucket/path",
        static_dir=tmp_path,
        storage_options={"endpoint_url": "https://s3.us-east-005.backblazeb2.com"},
    )

    assert state.root_path == "bucket/path"
    assert calls == [("s3://bucket/path", {"endpoint_url": "https://s3.us-east-005.backblazeb2.com"})]


def test_create_state_normalizes_empty_backend_root(monkeypatch, tmp_path):
    from fsspec_browser import web

    class FakeFs:
        root_marker = "/"

    monkeypatch.setattr(web.fsspec.core, "url_to_fs", lambda url, **kwargs: (FakeFs(), ""))

    state = web.create_state("db+duckdb://", static_dir=tmp_path)

    assert state.root_path == "/"


def test_list_entries_sorts_directories_first(tmp_path):
    from fsspec_browser import web

    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "nested.txt").write_text("a")

    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=tmp_path)
    listing = web.list_entries(state)

    assert [entry["name"] for entry in listing["entries"]] == ["a", "b.txt"]
    assert [entry["type"] for entry in listing["entries"]] == ["directory", "file"]


def test_list_entries_paginates_by_page_size(tmp_path):
    from fsspec_browser import web

    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")

    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=tmp_path, page_size=1)
    first = web.list_entries(state)
    second = web.list_entries(state, offset=first["next_offset"])

    assert [entry["name"] for entry in first["entries"]] == ["a.txt"]
    assert first["has_more"] is True
    assert first["next_offset"] == 1
    assert [entry["name"] for entry in second["entries"]] == ["b.txt"]
    assert second["has_more"] is False
    assert second["next_offset"] is None


def test_list_entries_deduplicates_backend_paths(tmp_path):
    from fsspec_browser import web

    class FakeFs:
        def ls(self, path, detail=True):
            return [
                {"name": "/main", "type": "directory"},
                {"name": "/main", "type": "directory"},
            ]

        def unstrip_protocol(self, path):
            return path

    state = web.BrowserState(FakeFs(), "/", "fake://", tmp_path, tmp_path, 1024, 256, 20)

    assert [entry["name"] for entry in web.list_entries(state)["entries"]] == ["main"]


def test_normalize_entry_includes_metadata():
    from fsspec_browser import web

    class FakeFs:
        def unstrip_protocol(self, path):
            return f"protocol://{path}"

    entry = web._normalize_entry(
        FakeFs(),
        {
            "LastModified": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            "created": 0,
            "etag": "abc",
            "name": "bucket/data.json",
            "size": 12,
            "type": "file",
        },
    )

    assert entry["metadata"] == {
        "created": "1970-01-01T00:00:00+00:00",
        "modified": "2026-01-02T03:04:05+00:00",
        "etag": "abc",
    }


def test_data_source_directories_preview_rows_or_metadata():
    from fsspec_data import Facet

    from fsspec_browser import web

    relation = {"name": "/main/orders", "type": "directory", "kind": "view"}
    entry = web._normalize_entry(object(), relation, frozenset({Facet.CHILDREN, Facet.TABLE, Facet.METADATA}))
    assert entry["previewable"] is True
    assert entry["facets"] == ["children", "metadata", "table"]
    assert web._normalize_entry(object(), relation, frozenset({Facet.CHILDREN}))["previewable"] is False
    assert web._normalize_entry(object(), relation)["previewable"] is False
    column = {"name": "/main/orders/columns/id", "type": "file"}
    assert web._normalize_entry(object(), column, frozenset({Facet.METADATA}))["previewable"] is True
    assert web._normalize_entry(object(), column, frozenset())["previewable"] is False


def test_preview_file_formats_json(tmp_path):
    from fsspec_browser import web

    path = tmp_path / "data.json"
    path.write_text('{"b": 1, "a": 2}')

    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=tmp_path)
    preview = web.preview_file(state, str(path))

    assert preview["kind"] == "json"
    assert preview["content"] == '{\n  "a": 2,\n  "b": 1\n}'
    assert preview["columns"] == []
    assert preview["rows"] == []
    assert preview["continuation"] is None
    assert preview["offset"] == 0
    assert preview["limit"] is None
    assert set(preview) == {
        "columns",
        "content",
        "continuation",
        "display_path",
        "kind",
        "limit",
        "metadata",
        "offset",
        "path",
        "rows",
        "size",
        "truncated",
    }


def test_preview_file_does_not_format_truncated_json(tmp_path):
    from fsspec_browser import web

    path = tmp_path / "data.json"
    path.write_text('{"b": 1, "a": 2}')

    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=tmp_path)
    preview = web.preview_file(state, str(path), max_bytes=8)

    assert preview["kind"] == "text"
    assert preview["content"] == '{"b": 1,'
    assert preview["truncated"] is True


def test_preview_tabular_files_are_paged(tmp_path):
    from fsspec_browser import web

    csv_path = tmp_path / "data.csv"
    csv_path.write_text("name,score\nada,2\ngrace,3\nlin,4\n")
    jsonl_path = tmp_path / "data.jsonl"
    jsonl_path.write_text('{"name":"ada","score":2}\n{"name":"grace","score":3}\n{"name":"lin","score":4}\n')
    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=tmp_path, preview_rows=2)

    csv_page = web.preview_file(state, str(csv_path))
    jsonl_page = web.preview_file(state, str(jsonl_path), offset=2)

    assert csv_page["rows"] == [{"name": "ada", "score": 2}, {"name": "grace", "score": 3}]
    assert csv_page["continuation"] == {"kind": "offset", "value": 2}
    assert jsonl_page["rows"] == [{"name": "lin", "score": 4}]
    assert jsonl_page["continuation"] is None


@pytest.mark.parametrize("format", ["arrow", "parquet"])
def test_preview_embedded_schema_formats_use_fsspec_data(tmp_path, monkeypatch, format):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from fsspec_browser import web

    table = pa.table({"name": ["ada", "grace", "lin"], "score": [2, 3, 4]})
    path = tmp_path / f"data.{format}"
    if format == "arrow":
        with path.open("wb") as file, pa.ipc.new_stream(file, table.schema) as writer:
            writer.write_table(table)
    else:
        pq.write_table(table, path)

    calls = []
    get_codec = web.DEFAULT_REGISTRY.get

    class RecordingCodec:
        def __init__(self, codec):
            self.codec = codec

        def iter_batches(self, source, **kwargs):
            calls.append((source, kwargs))
            return self.codec.iter_batches(source, **kwargs)

    monkeypatch.setattr(web.DEFAULT_REGISTRY, "get", lambda data_format: RecordingCodec(get_codec(data_format)))
    state = web.create_state(
        str(tmp_path),
        static_dir=tmp_path,
        download_root=tmp_path,
        preview_bytes=1024 * 1024,
        preview_rows=2,
    )

    preview = web.preview_file(state, str(path))
    continuation = preview["continuation"]
    assert continuation is not None
    next_preview = web.preview_file(state, str(path), offset=int(continuation["value"]))

    assert preview["columns"] == ["name", "score"]
    assert preview["rows"] == [{"name": "ada", "score": 2}, {"name": "grace", "score": 3}]
    assert preview["continuation"] == {"kind": "offset", "value": 2}
    assert next_preview["rows"] == [{"name": "lin", "score": 4}]
    assert next_preview["continuation"] is None
    assert len(calls) == 2
    assert hasattr(calls[0][0], "read")
    assert calls[0][1] == {"batch_size": 3, "byte_limit": 1024 * 1024, "row_limit": 3, "schema": None}
    assert calls[1][1] == {"batch_size": 3, "byte_limit": 1024 * 1024, "row_limit": 5, "schema": None}


def test_text_table_previews_use_matching_schemas(tmp_path):
    import pyarrow as pa

    from fsspec_browser import web

    csv_path = tmp_path / "2026" / "scores.csv"
    csv_path.parent.mkdir()
    csv_path.write_text("name,score\nada,2\ngrace,3\n")
    floats = pa.schema([("name", pa.string()), ("score", pa.float64())])
    state = web.create_state(
        str(tmp_path),
        static_dir=tmp_path,
        download_root=tmp_path,
        table_schemas=[("*.jsonl", pa.schema([("x", pa.int8())])), ("*/2026/*.csv", floats)],
    )

    page = web.preview_file(state, str(csv_path))

    assert page["rows"] == [{"name": "ada", "score": 2.0}, {"name": "grace", "score": 3.0}]
    assert isinstance(page["rows"][0]["score"], float)
    state.table_schemas = (("*.csv", pa.schema([("name", pa.int64()), ("score", pa.int64())])),)
    with pytest.raises(ValueError):
        web.preview_file(state, str(csv_path))


def test_text_tables_fall_back_when_inferred_schemas_do_not_fit(tmp_path):
    from fsspec_browser import web

    scalars = tmp_path / "scalars.jsonl"
    scalars.write_text("1\n2\n")
    later = tmp_path / "later.csv"
    later.write_text("name,score\nada,2\ngrace,x\n")
    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=tmp_path, preview_bytes=10)

    assert web.preview_file(state, str(scalars))["rows"] == [{"value": 1}, {"value": 2}]
    assert web.preview_file(state, str(later))["rows"] == [{"name": "ada", "score": "2"}, {"name": "grace", "score": "x"}]


def test_schema_options_resolve_references(tmp_path):
    import pyarrow as pa

    from fsspec_browser import web

    schema_path = tmp_path / "scores.json"
    schema_path.write_text(json.dumps({"fields": [{"name": "name", "type": "string"}, {"name": "score", "type": "float64"}]}))
    args = web._parse_args(["--schema", f"*.csv=arrow-json:{schema_path}", f"--schema=*.jsonl=s3://bucket/{schema_path.name}"])

    assert args.schema[0][1].format == "arrow-json"
    assert args.schema[1][1].url == "s3://bucket/scores.json"
    assert args.schema[1][1].format is None
    assert web._table_schemas(args.schema[:1]) == (("*.csv", pa.schema([("name", pa.string()), ("score", pa.float64())])),)
    with pytest.raises(SystemExit):
        web._parse_args(["--schema", "*.csv"])


def test_sessions_keep_server_table_schemas(tmp_path):
    import pyarrow as pa

    from fsspec_browser import web

    schemas = (("*.csv", pa.schema([("name", pa.string())])),)
    server = web.create_server("127.0.0.1", 0, None, static_dir=tmp_path, download_root=tmp_path, table_schemas=schemas)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _host, port = server.server_address[:2]
        connection = HTTPConnection("127.0.0.1", port)
        connection.request(
            "POST",
            "/api/session",
            body=json.dumps({"path": str(tmp_path)}).encode(),
            headers={
                "content-type": "application/json",
                "host": f"127.0.0.1:{port}",
                "x-fsspec-browser-token": server.token,
            },
        )
        assert connection.getresponse().status == 200
        assert server.state is not None
        assert server.state.table_schemas == schemas
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_preview_kafka_partition_pages_by_offset_token(tmp_path):
    from fsspec_browser import web

    # Offsets 3, 5, 6 and 9 remain after compaction.
    messages = {offset: {"partition": 0, "offset": offset, "value": f"v{offset}"} for offset in (3, 5, 6, 9)}

    from fsspec_data import DataSource, Facet, Node

    class FakeKafkaFs(DataSource):
        protocol = ("kafka", "kafka+offset")

        def info(self, path):
            return {"name": path, "type": "directory", "size": 0, "kind": "partition", "partition": "0", "low": "3", "high": "10"}

        def describe(self, path):
            return Node(path, [Facet.CHILDREN, Facet.TABLE, Facet.METADATA])

        def cat_file(self, path):
            name, query = path.split("?")
            assert name == "orders/0.jsonl"
            params = dict(part.split("=") for part in query.split("&"))
            start, limit = int(params["start"]), int(params["limit"])
            rows = [message for offset, message in messages.items() if offset >= start][:limit]
            return "".join(json.dumps(row) + "\n" for row in rows).encode()

        def unstrip_protocol(self, path):
            return f"kafka://{path}"

    fs = FakeKafkaFs()
    assert web._normalize_entry(fs, fs.info("orders/0"), fs.describe("orders/0").facets)["previewable"] is True

    state = web.BrowserState(fs, "", "kafka://", tmp_path, tmp_path, 1024, 256, 2)
    first = web.preview_file(state, "orders/0/")
    assert [row["offset"] for row in first["rows"]] == [3, 5]
    assert first["continuation"] == {"kind": "token", "value": "6"}

    second = web.preview_file(state, "orders/0", token=str(first["continuation"]["value"]))
    assert [row["offset"] for row in second["rows"]] == [6, 9]
    assert second["continuation"] is None


def test_preview_database_relation_and_sql(tmp_path):
    from fsspec_browser import web

    class FakeTable:
        num_columns = 2

        def __init__(self, rows):
            self.rows = rows
            self.num_rows = len(rows)

        def slice(self, offset, length):
            return FakeTable(self.rows[offset : offset + length])

        def to_pylist(self):
            return self.rows

    import pyarrow as pa
    from fsspec_data import DataSource, Facet, Node

    sales = pa.table({"Region": ["East", "West", "South"], "Sales": [2, 3, 4]})

    class FakeDatabaseFs(DataSource):
        def info(self, path):
            return {"name": path, "type": "directory", "kind": "view", "size": None}

        def describe(self, path):
            return Node(path, [Facet.CHILDREN, Facet.TABLE, Facet.METADATA])

        def scan(self, path, *, batch_size=1024, row_limit=None, byte_limit=None):
            assert (path, row_limit) == ("/main/sales_by_region", 3)
            return pa.RecordBatchReader.from_batches(sales.schema, sales.to_batches(max_chunksize=batch_size))

        def query(self, sql):
            assert sql == ("SELECT * FROM (SELECT Region, Sales FROM sales_by_region) AS __fsspec_browser_preview LIMIT 3")
            return FakeTable([{"Region": "East", "Sales": 2}, {"Region": "West", "Sales": 3}, {"Region": "South", "Sales": 4}])

        def unstrip_protocol(self, path):
            return f"db+duckdb://{path}"

    state = web.BrowserState(FakeDatabaseFs(), "/", "db+duckdb://", tmp_path, tmp_path, 1024, 256, 2)

    relation = web.preview_file(state, "/main/sales_by_region")
    query = web.preview_query(state, "SELECT Region, Sales FROM sales_by_region")

    assert relation["kind"] == "table"
    assert relation["columns"] == ["Region", "Sales"]
    assert relation["rows"] == [{"Region": "East", "Sales": 2}, {"Region": "West", "Sales": 3}]
    assert relation["continuation"] == {"kind": "offset", "value": 2}
    assert relation["truncated"] is True
    assert json.loads(relation["content"]) == [{"Region": "East", "Sales": 2}, {"Region": "West", "Sales": 3}]
    assert query["kind"] == "table"
    assert query["columns"] == ["Region", "Sales"]
    assert query["rows"] == [{"Region": "East", "Sales": 2}, {"Region": "West", "Sales": 3}]
    assert query["continuation"] is None
    assert query["truncated"] is True

    try:
        web.preview_query(state, "DROP TABLE orders")
    except ValueError as exc:
        assert "SELECT or WITH" in str(exc)
    else:
        raise AssertionError("SQL preview should reject mutating statements")


# A data source with a relation, a metadata-only column, a raw file, and a plain folder.
_CATALOG = {
    "/": {"name": "/", "type": "directory", "size": 0},
    "/orders": {"name": "/orders", "type": "directory", "size": 0, "kind": "table"},
    "/orders/id": {"name": "/orders/id", "type": "file", "size": 0, "kind": "column"},
    "/notes.txt": {"name": "/notes.txt", "type": "file", "size": 5},
    "/folder": {"name": "/folder", "type": "directory", "size": 0},
}


def _catalog_fs():
    import pyarrow as pa
    from fsspec_data import DataSource, Facet, Node

    facets = {
        "/": [Facet.CHILDREN],
        "/orders": [Facet.CHILDREN, Facet.TABLE, Facet.METADATA],
        "/orders/id": [Facet.METADATA],
        "/notes.txt": [Facet.RAW],
        "/folder": [Facet.CHILDREN],
    }
    rows = pa.table({"id": list(range(5))})

    class CatalogFs(DataSource):
        def info(self, path):
            return dict(_CATALOG[path.rstrip("/") or "/"])

        def ls(self, path, detail=True):
            prefix = path.rstrip("/") + "/"
            return [dict(entry) for name, entry in _CATALOG.items() if name.startswith(prefix) and "/" not in name[len(prefix) :] and name != "/"]

        def describe(self, path):
            return Node(path, facets[path.rstrip("/") or "/"])

        def children(self, path):
            return [self.describe(entry["name"]) for entry in self.ls(path)]

        def scan(self, path, *, batch_size=1024, row_limit=None, byte_limit=None):
            return pa.RecordBatchReader.from_batches(rows.schema, rows.to_batches(max_chunksize=2))

        def metadata(self, path):
            return {"kind": "column", "arrow_type": "int64", "primary_key": True}

        def open(self, path, mode="rb"):
            import io

            return io.BytesIO(b"hello")

        def unstrip_protocol(self, path):
            return f"catalog://{path}"

    return CatalogFs()


def test_data_sources_list_and_preview_by_facet(tmp_path):
    from fsspec_browser import web

    state = web.BrowserState(_catalog_fs(), "/", "catalog://", tmp_path, tmp_path, 1024, 256, 2)

    listing = {entry["name"]: entry for entry in web.list_entries(state)["entries"]}
    assert {name: (entry["facets"], entry["previewable"]) for name, entry in listing.items()} == {
        "folder": (["children"], False),
        "orders": (["children", "metadata", "table"], True),
        "notes.txt": (["raw"], True),
    }

    first = web.preview_file(state, "/orders")
    second = web.preview_file(state, "/orders", offset=2)
    assert (first["rows"], first["continuation"]) == ([{"id": 0}, {"id": 1}], {"kind": "offset", "value": 2})
    assert second["rows"] == [{"id": 2}, {"id": 3}]

    column = web.preview_file(state, "/orders/id")
    assert column["kind"] == "json"
    assert json.loads(column["content"]) == {"arrow_type": "int64", "kind": "column", "primary_key": True}

    assert web.preview_file(state, "/notes.txt")["content"] == "hello"
    with pytest.raises(IsADirectoryError):
        web.preview_file(state, "/folder")


def test_download_target_strips_protocol(tmp_path):
    from fsspec_browser import web

    target = web._download_target("protocol://some/path/to/file.json", tmp_path)

    assert target == tmp_path / "some" / "path" / "to" / "file.json"


def test_download_file_copies_to_protocol_shaped_path(tmp_path, monkeypatch):
    from fsspec_browser import web

    source = tmp_path / "remote" / "file.json"
    source.parent.mkdir()
    source.write_text("{}")
    downloads = tmp_path / "downloads"
    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=downloads)
    monkeypatch.setattr(web, "_display_path", lambda _fs, _path: "protocol://some/path/to/file.json")

    result = web.download_file(state, str(source))

    assert Path(result["local_path"]).read_text() == "{}"
    assert Path(result["local_path"]).relative_to(downloads) == Path("some/path/to/file.json")
