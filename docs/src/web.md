# How to connect the web browser

Install the browser and the backend packages required by your URLs:

```console
python -m pip install fsspec-browser s3fs
```

## Connect a filesystem

Start a local session or pass a remote URL:

```console
fsspec-browser-web /tmp --host 127.0.0.1 --port 8765
fsspec-browser-web s3://bucket/path -o anon=true
```

To choose a connection in the UI, omit the path:

```console
fsspec-browser-web --host 127.0.0.1 --port 8765
```

Enter the path or URL and backend storage options in the connection form.
Use repeated `-o KEY=VALUE` arguments when supplying storage options at launch.

## Preview and download

Expand directories by clicking them. Scroll to reveal further entries. Select a
file for its metadata, then choose **Preview** or double-click it to read data.
Scroll near the end of a table preview to request another row page.

Use **Refresh** to reload the selected directory level and **Download** to copy a
file. Set the download destination and preview limits at launch:

```console
fsspec-browser-web /tmp --download-root downloads \
  --preview-rows 20 --preview-bytes 1048576
```

## Browse a DuckDB database

From a source checkout, install the database extra and create its fixture:

```console
python -m pip install 'fsspec-browser[database]'
python examples/create_superstore_duckdb.py
fsspec-browser-web db+duckdb:// \
  -o database=examples/superstore.duckdb --preview-rows 20
```

Select a table or view to browse metadata; choose **Preview** for rows. Use
**SQL Preview** for a read query when the backend supports `query()`.

For your own database, pass its file path with `-o database=...`. Consult the
[command-line reference](cli.md) for defaults and the scope of preview limits.
