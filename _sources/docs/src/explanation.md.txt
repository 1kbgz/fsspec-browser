# Why browsing and previewing are separate operations

`fsspec-browser` treats filesystem navigation, data retrieval, and rendering as separate
concerns. This makes one browser usable across local files, object stores, database
relations, and any other installed fsspec backend.

## fsspec is the compatibility boundary

The browser asks a backend for familiar operations such as `ls`, `info`, `open`, and
`get_file`. It does not need a frontend-specific implementation for every storage system.
Plain local paths and S3 can use native Rust backends in the terminal application; other
installed protocols cross the `fsspec-rs` Python bridge. The web server resolves all URLs
through Python fsspec.

This boundary gives the browser broad backend coverage, while backend packages retain
ownership of authentication, path rules, metadata, and query behavior.

## Selection does not imply an unbounded read

Listings and metadata are normally cheap compared with downloading an object or
materializing a database relation. For that reason, selecting an entry first displays its
metadata. Remote file previews require an explicit action, and every preview has byte or
row limits.

Database relations remain directory-like so users can browse columns, indexes, and
constraints. The browser recognizes relation metadata and requests a bounded data view
when previewing, rather than treating the directory as a conventional file.

## Rendering belongs to the frontend

Backends return bytes, metadata, or Arrow tables; they do not decide how those values look
on screen. The terminal renderer optimizes for a fixed cell grid and keyboard navigation.
The web renderer can use scrollable tables and request another page near the end of the
current one.

CSV, JSON, JSONL, and Parquet need format-aware renderers to be useful, but decoding them
does not change filesystem semantics. Keeping rendering in the browser prevents display
concerns from leaking into storage backends.

## Pagination protects interactive work

Directory paging limits how much metadata the UI presents at once. Preview paging limits
rows, while the byte limit bounds generic file reads. These controls serve responsiveness
and resource safety; they are not query correctness guarantees.

Database backends can make paging efficient by pushing `limit` and `offset` into a query.
Generic files may still require sequential decoding to reach a later page. The same UI
gesture therefore has backend-dependent cost even though its result looks consistent.

## See also

- Follow the [local preview tutorial](tutorial.md).
- Use the [terminal](terminal.md) or [web](web.md) guide.
- Look up the [Python API](api.md).
