"""Previews of fsspec-data data sources, shared by the web and terminal browsers.

A filesystem that describes its own nodes, such as fsspec-db, fsspec-kafka, or a data view,
is previewed by each node's facets: rows for a table, bytes for a raw file, and metadata
otherwise. Other filesystems are previewed by file type."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from fsspec_data import DataSource, Facet


def as_source(fs: Any) -> DataSource | None:
    """The filesystem as a data source, or ``None`` when it does not describe its nodes."""
    return fs if isinstance(fs, DataSource) else None


def is_directory(info: dict[str, Any]) -> bool:
    return info.get("type") in {"directory", "dir"} or bool(info.get("isdir"))


def previewable(directory: bool, facets: frozenset[Facet] | None) -> bool:
    """Files preview by type. A data source's directories preview their rows or metadata, and
    its files preview whenever they offer something to show."""
    if facets is None:
        return not directory
    shown = {Facet.TABLE, Facet.METADATA} if directory else {Facet.TABLE, Facet.RAW, Facet.METADATA}
    return bool(facets & shown)


def is_kafka_partition(fs: Any, info: dict[str, Any]) -> bool:
    """A Kafka partition, which pages by message offset rather than row count, since
    compaction leaves gaps that a data source's scan cannot resume from yet."""
    protocol = getattr(fs, "protocol", ())
    protocols = (protocol,) if isinstance(protocol, str) else protocol
    return any(name.startswith("kafka") for name in protocols) and is_directory(info) and info.get("kind") == "partition"


def page_rows(batches: Iterable[Any], offset: int, wanted: int) -> list[dict[str, Any]]:
    """Up to ``wanted`` rows after skipping ``offset`` rows of ``batches``."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for batch in batches:
        batch_rows = batch.to_pylist()
        if skipped + len(batch_rows) <= offset:
            skipped += len(batch_rows)
            continue
        start = max(offset - skipped, 0)
        rows.extend(batch_rows[start : start + wanted - len(rows)])
        skipped += len(batch_rows)
        if len(rows) >= wanted:
            break
    return rows


def table_rows(source: DataSource, path: str, offset: int, wanted: int, byte_limit: int | None) -> list[dict[str, Any]]:
    """Up to ``wanted`` rows of a table after ``offset`` rows."""
    batches = source.scan(path, batch_size=wanted, row_limit=offset + wanted, byte_limit=byte_limit)
    return page_rows(batches, offset, wanted)


def node_preview(source: DataSource, path: str, info: dict[str, Any]) -> str | None:
    """What a node previews as: ``"table"``, ``"metadata"``, or ``None`` for a file previewed
    by its type. Raises ``IsADirectoryError`` for a directory with nothing to show."""
    node = source.describe(path)
    directory = is_directory(info)
    if node.has(Facet.TABLE) and (directory or node.native_format is None):
        return "table"
    if not directory and (node.has(Facet.TABLE) or node.has(Facet.RAW)):
        return None
    if node.has(Facet.METADATA):
        return "metadata"
    if directory:
        raise IsADirectoryError(path)
    return None


def metadata_json(source: DataSource, path: str) -> str:
    return json.dumps(source.metadata(path), indent=2, sort_keys=True, default=str)


def terminal_previewable(fs: Any, path: str, directory: bool) -> bool:
    """Whether the terminal browser previews ``path``."""
    source = as_source(fs)
    return previewable(directory, source.describe(path).facets if source is not None else None)


def terminal_page(fs: Any, path: str, offset: int, rows: int, byte_limit: int | None) -> tuple[bytes, bool] | None:
    """A terminal preview page of a data source node: a JSON array of up to ``rows`` rows
    and whether more follow, or metadata as JSON. ``None`` means the file is previewed as
    bytes."""
    source = as_source(fs)
    if source is None:
        return None
    info = fs.info(path)
    kind = node_preview(source, path, info)
    if kind == "table":
        page = table_rows(source, path, offset, rows + 1, byte_limit)
        return json.dumps(page[:rows], default=str).encode(), len(page) > rows
    if kind == "metadata":
        return metadata_json(source, path).encode(), False
    return None
