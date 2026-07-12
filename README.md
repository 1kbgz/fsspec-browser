# fsspec-browser

Terminal and web browser for fsspec-backed filesystems.

[![Build Status](https://github.com/1kbgz/fsspec-browser/actions/workflows/build.yaml/badge.svg?branch=main&event=push)](https://github.com/1kbgz/fsspec-browser/actions/workflows/build.yaml)
[![codecov](https://codecov.io/gh/1kbgz/fsspec-browser/branch/main/graph/badge.svg)](https://codecov.io/gh/1kbgz/fsspec-browser)
[![License](https://img.shields.io/github/license/1kbgz/fsspec-browser)](https://github.com/1kbgz/fsspec-browser)
[![PyPI](https://img.shields.io/pypi/v/fsspec-browser.svg)](https://pypi.python.org/pypi/fsspec-browser)

## Overview

`fsspec-browser` lets you inspect local files, object stores, and other fsspec-compatible filesystems from a terminal UI or a local web UI. It is built for browsing, previewing, and downloading files without writing one-off scripts.

![fsspec-browser web UI](docs/img/browser.png)

![fsspec-browser terminal UI](docs/img/terminal.png)

## Install

```bash
pip install fsspec-browser
```

Install any fsspec backend packages your URLs require, such as S3, GCS, SSH, or cloud vendor integrations.

## Terminal Browser

```bash
fsspec-browser /tmp
fsspec-browser s3-rs://my-bucket/path -o endpoint_url=https://...
```

Use `Ctrl-A`, then `Left` or `Right`, to focus the browser or preview pane. Arrow keys operate on the focused pane: they navigate files in the browser and scroll vertically or horizontally in the preview. `Enter` opens directories, `p` previews remote files, and `d` downloads the selected file. `Ctrl-U`/`Ctrl-D` and `H`/`L` remain preview scrolling shortcuts. Database previews fetch another 100-row page near the end.

## Web Browser

```bash
fsspec-browser-web /tmp --host 127.0.0.1 --port 8765
fsspec-browser-web --host 127.0.0.1 --port 8765
```

When started without a path, the web UI opens a connection form. File previews are explicit and bounded by `--preview-bytes`. Database relations and columns, CSV, JSON/JSONL, and Parquet render as tables. Scrolling the preview loads the next `--preview-rows` page.

### Browse a DuckDB database

Install the database extra and create the Superstore fixture:

```bash
pip install 'fsspec-browser[database]'
python examples/create_superstore_duckdb.py
```

Start the web browser with the DuckDB database as a storage option:

```bash
fsspec-browser-web db+duckdb:// \
  -o database=examples/superstore.duckdb \
  --preview-rows 20
```

Tables and stored views remain directory-like database relations, but are explicitly
previewable as bounded row sets. Use **SQL Preview** for an arbitrary read query.

## Documentation

See the full docs for terminal usage, web usage, and Python API reference.
