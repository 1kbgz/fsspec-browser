import json
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread


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


def test_normalize_entry_includes_metadata():
    from fsspec_browser import web

    class FakeFs:
        def unstrip_protocol(self, path):
            return f"protocol://{path}"

    entry = web._normalize_entry(
        FakeFs(),
        {
            "LastModified": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
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


def test_preview_file_formats_json(tmp_path):
    from fsspec_browser import web

    path = tmp_path / "data.json"
    path.write_text('{"b": 1, "a": 2}')

    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=tmp_path)
    preview = web.preview_file(state, str(path))

    assert preview["kind"] == "json"
    assert preview["content"] == '{\n  "a": 2,\n  "b": 1\n}'


def test_preview_file_does_not_format_truncated_json(tmp_path):
    from fsspec_browser import web

    path = tmp_path / "data.json"
    path.write_text('{"b": 1, "a": 2}')

    state = web.create_state(str(tmp_path), static_dir=tmp_path, download_root=tmp_path)
    preview = web.preview_file(state, str(path), max_bytes=8)

    assert preview["kind"] == "text"
    assert preview["content"] == '{"b": 1,'
    assert preview["truncated"] is True


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
