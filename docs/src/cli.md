# Command-line reference

## Terminal command

```text
fsspec-browser [url] [options]
```

An omitted URL starts an interactive session prompt. Plain local paths and
`local-rs://` use the native local backend; `s3://` and `s3-rs://` use native S3.
Other registered protocols use the Python fsspec bridge.

| Option                             | Default     | Meaning                                           |
| ---------------------------------- | ----------- | ------------------------------------------------- |
| `-o`, `--storage-option KEY=VALUE` | none        | Repeated backend options.                         |
| `--page-size`                      | `256`       | Entries fetched or revealed per page.             |
| `--preview-bytes`                  | `104857600` | Raw preview bytes or decoded Arrow-memory budget. |
| `--preview-rows`                   | `20`        | Rows per tabular preview page.                    |
| `-h`, `--help`                     | off         | Command help.                                     |

Native S3 accepts `endpoint_url`, `region`, `key` / `access_key_id`,
`secret` / `secret_access_key`, `token` / `session_token`, `skip_signature`, and
`allow_http`. Bridged backends use their own storage-option names.

### Terminal keys

`Ctrl-A`, then `Left` or `Right`, selects the browser or preview pane. Arrow,
page, home, and end keys operate on the focused pane. With browser focus:

| Key                      | Action                         |
| ------------------------ | ------------------------------ |
| `j`, `Down`              | Move down                      |
| `k`, `Up`                | Move up                        |
| `Enter`, `l`, `Right`    | Enter selected directory       |
| `h`, `Left`, `Backspace` | Go to parent directory         |
| `Space`                  | Expand or collapse a directory |
| `PageUp`, `PageDown`     | Move by a page                 |
| `g`, `Home`              | Move to top                    |
| `G`, `End`               | Move to bottom                 |
| `p`                      | Preview selected file          |
| `d`                      | Download selected file         |
| `r`                      | Refresh current directory      |
| `n`                      | Start a new session            |
| `q`, `Esc`, `Ctrl-C`     | Quit                           |

With preview focus, arrows scroll vertically or horizontally; page keys scroll
vertically, and home/end move to the start/end. `Ctrl-U` and `Ctrl-D` scroll the
preview vertically, and `H` and `L` scroll it horizontally from either pane.

### Terminal previews and downloads

Local files can preview on selection; remote reads require `p`. Complete JSON is
pretty-printed; truncated JSON stays raw. Arrow IPC (`.arrow`, `.ipc`) and Parquet
(`.parquet`, `.pq`) render as tables through `fsspec-data`. Scrolling near the end
loads another row page.

Downloads use the current working directory and a relative path derived from the
selected URL.

## Web command

```text
fsspec-browser-web [path] [options]
```

An omitted path opens a connection form. All sessions use Python fsspec.

| Option                             | Default     | Description                                |
| ---------------------------------- | ----------- | ------------------------------------------ |
| `path`                             | none        | fsspec URL or local path to browse         |
| `-o`, `--storage-option KEY=VALUE` | none        | Backend option; may be repeated            |
| `--host`                           | `127.0.0.1` | Server host                                |
| `--port`                           | `0`         | Server port; `0` chooses an available port |
| `--page-size`                      | `256`       | Entries revealed per directory page        |
| `--preview-bytes`                  | `1048576`   | Maximum bytes read for file preview        |
| `--preview-rows`                   | `20`        | Rows returned per structured preview page  |
| `--download-root`                  | `.`         | Directory where downloads are written      |
| `--no-open`                        | off         | Do not open a browser tab                  |

### Web previews and downloads

Selecting a file displays metadata. **Preview** or a double-click reads it.
Directories expand on click and reveal more entries while scrolling. **Refresh**
reloads the selected directory level.

Raw previews request at most `--preview-bytes + 1` bytes to detect truncation.
Complete `.json` previews are formatted. CSV, JSON/JSONL, Arrow IPC, Parquet, and
database relations can render as tables. Arrow IPC and Parquet use row and decoded
Arrow-memory bounds. The byte option is not a universal cap on backend traffic or
on all structured decoders' allocations.

**SQL Preview** is available when the filesystem provides `query()`. It accepts
`SELECT` and `WITH` and wraps the query with a row limit.

Downloads are copied to `--download-root`. Target paths remove protocol parts and
unsafe `.` or `..` components. Metadata fields depend on the backend.
