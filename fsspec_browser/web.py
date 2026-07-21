"""Web entrypoint for browsing fsspec filesystems."""

from __future__ import annotations

import argparse
import csv
import ipaddress
import itertools
import json
import mimetypes
import secrets
import shutil
import sys
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal, Sequence, TypedDict
from urllib.parse import parse_qs, unquote, urlparse

import fsspec

MAX_PREVIEW_BYTES = 1 * 1024 * 1024
_METADATA_KEYS = (
    ("created", "created"),
    ("ctime", "created"),
    ("modified", "modified"),
    ("mtime", "modified"),
    ("last_modified", "modified"),
    ("LastModified", "modified"),
    ("updated", "updated"),
    ("atime", "accessed"),
    ("etag", "etag"),
    ("ETag", "etag"),
    ("content_type", "content type"),
    ("ContentType", "content type"),
)
_TIMESTAMP_KEYS = {"atime", "created", "ctime", "modified", "mtime"}


class PreviewContinuation(TypedDict):
    kind: Literal["offset"]
    value: int


class PreviewPage(TypedDict):
    columns: list[str]
    content: str
    continuation: PreviewContinuation | None
    display_path: str
    kind: Literal["binary", "json", "table", "text"]
    limit: int | None
    metadata: dict[str, str]
    offset: int
    path: str
    rows: list[dict[str, Any]]
    size: int | None
    truncated: bool


@dataclass
class BrowserState:
    fs: Any
    root_path: str
    root_url: str
    static_dir: Path
    download_root: Path
    preview_bytes: int
    page_size: int
    preview_rows: int


class BrowserServer(ThreadingHTTPServer):
    state: BrowserState | None
    static_dir: Path
    download_root: Path
    page_size: int
    preview_bytes: int
    preview_rows: int
    token: str


def _default_static_dir() -> Path:
    return Path(__file__).with_name("extension")


def _is_loopback_host(value: str | None) -> bool:
    if not value:
        return False
    host = value.rsplit("@", 1)[-1].strip().lower()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    else:
        host = host.split(":", 1)[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_state(
    root_url: str,
    *,
    static_dir: Path | None = None,
    download_root: Path | str = ".",
    page_size: int = 256,
    preview_bytes: int = MAX_PREVIEW_BYTES,
    preview_rows: int = 20,
    storage_options: dict[str, str] | None = None,
) -> BrowserState:
    fs, root_path = fsspec.core.url_to_fs(root_url, **(storage_options or {}))
    root_path = root_path or getattr(fs, "root_marker", "/")
    return BrowserState(
        fs=fs,
        root_path=root_path,
        root_url=root_url,
        static_dir=static_dir or _default_static_dir(),
        download_root=Path(download_root),
        preview_bytes=max(preview_bytes, 1),
        preview_rows=max(preview_rows, 1),
        page_size=max(page_size, 1),
    )


def _display_path(fs: Any, path: str) -> str:
    try:
        return str(fs.unstrip_protocol(path))
    except Exception:
        return path


def _entry_name(path: str) -> str:
    clean = path.rstrip("/")
    return clean.rsplit("/", 1)[-1] or clean


def _is_directory(entry: dict[str, Any]) -> bool:
    kind = entry.get("type")
    return kind in {"directory", "dir"} or bool(entry.get("isdir"))


def _format_metadata_value(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool) and key in _TIMESTAMP_KEYS:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    text = str(value)
    return text or None


def _metadata(entry: dict[str, Any]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, label in _METADATA_KEYS:
        if key not in entry or label in metadata:
            continue
        value = _format_metadata_value(key, entry[key])
        if value:
            metadata[label] = value
    return metadata


def _normalize_entry(fs: Any, entry: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(entry, str):
        entry = {"name": entry}
    path = str(entry.get("name") or entry.get("path") or "")
    item_type = "directory" if _is_directory(entry) else "file"
    return {
        "name": _entry_name(path),
        "path": path,
        "display_path": _display_path(fs, path),
        "type": item_type,
        "size": entry.get("size"),
        "metadata": _metadata(entry),
        "previewable": item_type == "file" or entry.get("kind") in {"table", "view"},
    }


def list_entries(state: BrowserState, path: str | None = None, *, offset: int = 0) -> dict[str, Any]:
    list_path = state.root_path if path is None else path
    raw_entries = state.fs.ls(list_path, detail=True)
    if isinstance(raw_entries, dict):
        raw_entries = list(raw_entries.values())
    normalized = [_normalize_entry(state.fs, entry) for entry in raw_entries]
    entries = list({(entry["path"], entry["type"]): entry for entry in normalized}.values())
    entries.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
    offset = max(offset, 0)
    next_offset = offset + state.page_size
    page = entries[offset:next_offset]
    return {
        "path": list_path,
        "display_path": _display_path(state.fs, list_path),
        "entries": page,
        "has_more": next_offset < len(entries),
        "next_offset": next_offset if next_offset < len(entries) else None,
    }


def _is_json_path(display_path: str) -> bool:
    return display_path.lower().endswith(".json")


def _preview_payload(
    state: BrowserState,
    path: str,
    info: dict[str, Any],
    *,
    kind: Literal["binary", "json", "table", "text"],
    content: str,
    columns: list[str] | None = None,
    rows: list[dict[str, Any]] | None = None,
    offset: int = 0,
    limit: int | None = None,
    continuation: PreviewContinuation | None = None,
    metadata: dict[str, str] | None = None,
    truncated: bool = False,
    display_path: str | None = None,
) -> PreviewPage:
    return {
        "path": path,
        "display_path": display_path or _display_path(state.fs, path),
        "size": info.get("size"),
        "kind": kind,
        "content": content,
        "columns": columns or [],
        "rows": rows or [],
        "offset": offset,
        "limit": limit,
        "continuation": continuation,
        "metadata": {**_metadata(info), **(metadata or {})},
        "truncated": truncated,
    }


def _table_payload(
    state: BrowserState,
    path: str,
    info: dict[str, Any],
    rows: list[dict[str, Any]],
    offset: int,
    *,
    allow_continuation: bool = True,
    display_path: str | None = None,
    metadata: dict[str, str] | None = None,
) -> PreviewPage:
    has_more = len(rows) > state.preview_rows
    rows = rows[: state.preview_rows]
    columns = list(rows[0]) if rows else []
    continuation = PreviewContinuation(kind="offset", value=offset + len(rows)) if has_more and allow_continuation else None
    return _preview_payload(
        state,
        path,
        info,
        kind="table",
        content=json.dumps(rows, indent=2, default=str),
        columns=columns,
        rows=rows,
        offset=offset,
        limit=state.preview_rows,
        continuation=continuation,
        metadata={"rows": str(len(rows)), **(metadata or {})},
        truncated=has_more,
        display_path=display_path,
    )


def _preview_delimited(state: BrowserState, path: str, info: dict[str, Any], offset: int) -> PreviewPage:
    with state.fs.open(path, "rt", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(itertools.islice(reader, offset, offset + state.preview_rows + 1))
    return _table_payload(state, path, info, rows, offset)


def _preview_jsonl(state: BrowserState, path: str, info: dict[str, Any], offset: int) -> PreviewPage:
    with state.fs.open(path, "rt") as file:
        lines = itertools.islice(file, offset, offset + state.preview_rows + 1)
        rows = [json.loads(line) for line in lines if line.strip()]
    if not all(isinstance(row, dict) for row in rows):
        rows = [{"value": row} for row in rows]
    return _table_payload(state, path, info, rows, offset)


def _preview_parquet(state: BrowserState, path: str, info: dict[str, Any], offset: int) -> PreviewPage:
    import pyarrow.parquet as pq

    wanted = state.preview_rows + 1
    rows: list[dict[str, Any]] = []
    skipped = 0
    with state.fs.open(path, "rb") as file:
        parquet = pq.ParquetFile(file)
        for batch in parquet.iter_batches(batch_size=wanted):
            batch_rows = batch.to_pylist()
            if skipped + len(batch_rows) <= offset:
                skipped += len(batch_rows)
                continue
            start = max(offset - skipped, 0)
            rows.extend(batch_rows[start : start + wanted - len(rows)])
            skipped += len(batch_rows)
            if len(rows) >= wanted:
                break
    return _table_payload(state, path, info, rows, offset)


def preview_file(state: BrowserState, path: str, *, max_bytes: int | None = None, offset: int = 0) -> PreviewPage:
    info = state.fs.info(path)
    if _is_directory(info):
        if info.get("kind") in {"table", "view"}:
            return _preview_relation(state, path, info, offset)
        raise IsADirectoryError(path)

    display_path = _display_path(state.fs, path)
    lower_path = display_path.lower()
    if info.get("kind") == "column":
        data = state.fs.cat_file(f"{path}?limit={state.preview_rows + 1}&offset={offset}")
        values = json.loads(data)
        return _table_payload(state, path, info, [{"value": value} for value in values], offset)
    if lower_path.endswith(".csv"):
        return _preview_delimited(state, path, info, offset)
    if lower_path.endswith((".jsonl", ".ndjson")):
        return _preview_jsonl(state, path, info, offset)
    if lower_path.endswith(".parquet"):
        return _preview_parquet(state, path, info, offset)

    max_bytes = state.preview_bytes if max_bytes is None else max(max_bytes, 1)
    with state.fs.open(path, "rb") as file:
        data = file.read(max_bytes + 1)

    truncated = len(data) > max_bytes
    data = data[:max_bytes]

    if b"\x00" in data:
        return _preview_payload(
            state,
            path,
            info,
            kind="binary",
            content="",
            truncated=truncated,
            display_path=display_path,
        )

    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        content = data.decode("utf-8", errors="replace")
        kind = "binary"
    else:
        kind = "text"

    if _is_json_path(display_path) and not truncated:
        try:
            value = json.loads(content)
            if isinstance(value, list):
                rows = [row if isinstance(row, dict) else {"value": row} for row in value]
                return _table_payload(
                    state,
                    path,
                    info,
                    rows[offset : offset + state.preview_rows + 1],
                    offset,
                )
            content = json.dumps(value, indent=2, sort_keys=True)
            kind = "json"
        except json.JSONDecodeError:
            pass

    return _preview_payload(
        state,
        path,
        info,
        kind=kind,
        content=content,
        truncated=truncated,
        display_path=display_path,
    )


def preview_query(state: BrowserState, sql: str) -> PreviewPage:
    sql = sql.strip().removesuffix(";")
    if not sql:
        raise ValueError("SQL query is empty")
    if sql.split(None, 1)[0].upper() not in {"SELECT", "WITH"}:
        raise ValueError("SQL preview only accepts SELECT or WITH queries")
    query = getattr(state.fs, "query", None)
    if query is None:
        raise TypeError("active filesystem does not support SQL queries")
    bounded_sql = f"SELECT * FROM ({sql}) AS __fsspec_browser_preview LIMIT {state.preview_rows + 1}"
    table = query(bounded_sql)
    rows = table.to_pylist()
    return _table_payload(
        state,
        "",
        {"size": None},
        rows,
        0,
        allow_continuation=False,
        display_path="SQL query",
        metadata={"columns": str(table.num_columns)},
    )


def _preview_relation(state: BrowserState, path: str, info: dict[str, Any], offset: int = 0) -> PreviewPage:
    clean_path = path.rstrip("/")
    data = state.fs.cat_file(f"{clean_path}.jsonl?limit={state.preview_rows + 1}&offset={offset}")
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line]
    result = _table_payload(state, path, info, rows, offset)
    result["metadata"]["relation"] = str(info["kind"])
    return result


def _download_target(display_path: str, download_root: Path) -> Path:
    parsed = urlparse(display_path)
    parts: list[str] = []
    if parsed.scheme:
        if parsed.netloc:
            parts.append(unquote(parsed.netloc))
        parts.extend(part for part in unquote(parsed.path).split("/") if part)
    else:
        parts.extend(part for part in display_path.split("/") if part)

    safe_parts = [part for part in parts if part not in {"", ".", ".."}]
    if not safe_parts:
        raise ValueError(f"cannot derive download path from {display_path!r}")

    root = download_root.resolve()
    target = root.joinpath(*safe_parts).resolve()
    target.relative_to(root)
    return target


def download_file(state: BrowserState, path: str) -> dict[str, str]:
    info = state.fs.info(path)
    if _is_directory(info):
        raise IsADirectoryError(path)

    display_path = _display_path(state.fs, path)
    target = _download_target(display_path, state.download_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with state.fs.open(path, "rb") as source, target.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    return {"path": path, "display_path": display_path, "local_path": str(target)}


def create_server(
    host: str,
    port: int,
    state: BrowserState | None,
    *,
    static_dir: Path | None = None,
    download_root: Path | str = ".",
    page_size: int = 256,
    preview_bytes: int = MAX_PREVIEW_BYTES,
    preview_rows: int = 20,
) -> BrowserServer:
    server = BrowserServer((host, port), BrowserRequestHandler)
    server.state = state
    server.static_dir = static_dir or _default_static_dir()
    server.download_root = Path(download_root)
    server.page_size = max(page_size, 1)
    server.preview_bytes = max(preview_bytes, 1)
    server.preview_rows = max(preview_rows, 1)
    server.token = secrets.token_urlsafe(32)
    return server


class BrowserRequestHandler(BaseHTTPRequestHandler):
    server: BrowserServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/") and not self._trusted_api_request():
                self._send_json({"error": "untrusted API request"}, HTTPStatus.FORBIDDEN)
                return
            if parsed.path == "/api/config":
                self._send_json(self._config_payload())
            elif parsed.path == "/api/list":
                state = self._active_state()
                query = parse_qs(parsed.query)
                offset = int(query.get("offset", ["0"])[0])
                self._send_json(list_entries(state, query.get("path", [None])[0], offset=offset))
            elif parsed.path == "/api/preview":
                state = self._active_state()
                query = parse_qs(parsed.query)
                path = query.get("path", [None])[0]
                if not path:
                    self._send_json({"error": "missing path"}, HTTPStatus.BAD_REQUEST)
                    return
                offset = int(query.get("offset", ["0"])[0])
                self._send_json(preview_file(state, path, offset=max(offset, 0)))
            else:
                self._send_static(parsed.path)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if not self._trusted_api_request():
                self._send_json({"error": "untrusted API request"}, HTTPStatus.FORBIDDEN)
                return
            if parsed.path == "/api/session":
                self._create_session()
                return
            if parsed.path == "/api/query":
                state = self._active_state()
                payload = self._read_json()
                self._send_json(preview_query(state, str(payload.get("sql") or "")))
                return
            if parsed.path != "/api/download":
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return

            state = self._active_state()
            payload = self._read_json()
            path = payload.get("path")
            if not path:
                self._send_json({"error": "missing path"}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(download_file(state, path))
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _active_state(self) -> BrowserState:
        if self.server.state is None:
            raise ValueError("no active browser session")
        return self.server.state

    def _trusted_browser_request(self) -> bool:
        if not _is_loopback_host(self.headers.get("host")):
            return False
        origin = self.headers.get("origin")
        if origin and not _is_loopback_host(urlparse(origin).hostname):
            return False
        return True

    def _trusted_api_request(self) -> bool:
        token = self.headers.get("x-fsspec-browser-token")
        return self._trusted_browser_request() and secrets.compare_digest(token or "", self.server.token)

    def _config_payload(self) -> dict[str, Any]:
        state = self.server.state
        if state is None:
            return {"active": False}
        return {
            "active": True,
            "root_path": state.root_path,
            "root_url": state.root_url,
            "display_root": _display_path(state.fs, state.root_path),
        }

    def _create_session(self) -> None:
        payload = self._read_json()
        root_url = str(payload.get("path") or "").strip()
        if not root_url:
            self._send_json({"error": "missing path"}, HTTPStatus.BAD_REQUEST)
            return
        storage_options = payload.get("storage_options") or {}
        if not isinstance(storage_options, dict):
            self._send_json({"error": "storage_options must be an object"}, HTTPStatus.BAD_REQUEST)
            return

        self.server.state = create_state(
            root_url,
            static_dir=self.server.static_dir,
            download_root=self.server.download_root,
            page_size=self.server.page_size,
            preview_bytes=self.server.preview_bytes,
            preview_rows=self.server.preview_rows,
            storage_options={str(key): str(value) for key, value in storage_options.items()},
        )
        self._send_json(self._config_payload())

    def _send_static(self, route: str) -> None:
        static_dir = self.server.static_dir.resolve()
        relative = unquote(route.lstrip("/") or "index.html")
        target = (static_dir / relative).resolve()
        try:
            target.relative_to(static_dir)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.name == "index.html":
            content_type = "text/html"
            html = data.decode("utf-8")
            token_meta = f'<meta name="fsspec-browser-token" content="{self.server.token}" />'
            data = html.replace("</head>", f"    {token_meta}\n  </head>", 1).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _parse_key_value(pair: str) -> tuple[str, str]:
    try:
        key, value = pair.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"storage option must be KEY=VALUE: {pair}") from exc
    if not key:
        raise argparse.ArgumentTypeError(f"storage option key is empty: {pair}")
    return key, value


def _storage_options(pairs: Sequence[tuple[str, str]]) -> dict[str, str]:
    return dict(pairs)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fsspec-browser-web")
    parser.add_argument("path", nargs="?", default=None, help="fsspec URL or local path to browse")
    parser.add_argument(
        "-o",
        "--storage-option",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        type=_parse_key_value,
        help="backend option. May be repeated",
    )
    parser.add_argument("--page-size", default=256, type=int, help="entries revealed per directory page")
    parser.add_argument("--preview-bytes", default=MAX_PREVIEW_BYTES, type=int, help="maximum file preview bytes")
    parser.add_argument("--preview-rows", default=20, type=int, help="maximum database rows per preview")
    parser.add_argument("--host", default="127.0.0.1", help="host for the local web server")
    parser.add_argument("--port", default=0, type=int, help="port for the local web server")
    parser.add_argument("--download-root", default=".", help="directory where downloads are written")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser tab")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    args.storage_options = _storage_options(args.storage_option)
    args.page_size = max(args.page_size, 1)
    args.preview_bytes = max(args.preview_bytes, 1)
    args.preview_rows = max(args.preview_rows, 1)
    return args


def run(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    state = (
        create_state(
            args.path,
            download_root=args.download_root,
            page_size=args.page_size,
            preview_bytes=args.preview_bytes,
            preview_rows=args.preview_rows,
            storage_options=args.storage_options,
        )
        if args.path
        else None
    )
    server = create_server(
        args.host,
        args.port,
        state,
        download_root=args.download_root,
        page_size=args.page_size,
        preview_bytes=args.preview_bytes,
        preview_rows=args.preview_rows,
    )
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    if not args.no_open:
        webbrowser.open(url)
    print(f"Serving fsspec-browser web UI at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
