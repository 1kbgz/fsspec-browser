# Terminal

`fsspec-browser` starts the terminal browser. It is useful for quick inspection from a shell, SSH session, or local development environment.

```bash
fsspec-browser /tmp
fsspec-browser local-rs:///tmp
fsspec-browser s3-rs://bucket/path -o endpoint_url=https://...
fsspec-browser s3://bucket/path -o key=... -o secret=...
```

Omit the path to enter backend details interactively.

## Supported Locations

Plain local paths and `local-rs://` URLs use the native local backend. `s3-rs://` and
`s3://` URLs use the native S3 backend. Any other protocol registered in the active
Python environment is loaded through fsspec and the `fsspec-rs` Python bridge.

Install the backend package required by the URL before starting the browser. For example,
install `fsspec-db` for `db+sqlite://` or `gcsfs` for `gs://`.

Storage options are passed with repeated `-o` or `--storage-option` flags:

```bash
fsspec-browser s3-rs://bucket/path \
  -o endpoint_url=https://s3.example.com \
  -o key=ACCESS_KEY \
  -o secret=SECRET_KEY
```

Useful S3 option names include `endpoint_url`, `region`, `key`, `access_key_id`, `secret`, `secret_access_key`, `token`, `session_token`, `skip_signature`, and `allow_http`.

## Navigation

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

## Previews

Local files can be previewed as you browse. Remote files require `p` before bytes are read, so selecting an object does not automatically download data.

Raw and text preview reads are bounded by `--preview-bytes`; default is 100 MiB. JSON
previews are pretty-printed when the complete preview is valid JSON. Truncated JSON stays
raw.

Arrow IPC (`.arrow` and `.ipc`) and Parquet (`.parquet` and `.pq`) previews render as tables.
Their decoding uses `fsspec-data` with explicit row and decoded Arrow-memory bounds. Change
the number of rows per page with `--preview-rows`; scrolling near the end loads the next
page.

```bash
fsspec-browser /tmp --preview-bytes 1048576 --preview-rows 20
```

## Paging And Downloads

Directory entries are loaded in pages. Change page size with `--page-size`:

```bash
fsspec-browser s3-rs://bucket/path --page-size 500
```

Downloads are written under the current working directory using a relative path derived from the selected file URL.
