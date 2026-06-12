# Web

`fsspec-browser-web` starts a local HTTP server and serves the bundled browser UI.

```bash
fsspec-browser-web /tmp --host 127.0.0.1 --port 8765
fsspec-browser-web s3://bucket/path -o anon=true
```

Omit the path to start without an active session. The UI will show a connection form where you can enter a path or URL and storage options.

```bash
fsspec-browser-web --host 127.0.0.1 --port 8765
```

## Filesystems

The web browser uses fsspec. Local paths work with the default install. Cloud and remote URLs may need their normal fsspec backend packages installed in the same Python environment.

Storage options are passed as repeated `-o` or `--storage-option` flags:

```bash
fsspec-browser-web s3://bucket/path \
  -o anon=false \
  -o key=ACCESS_KEY \
  -o secret=SECRET_KEY
```

## Browser Controls

Click directories to expand them. Large directories load more entries as you scroll near the end.

Selecting a file shows details and metadata. Use the `Preview` button or double-click a file to read preview bytes. This keeps remote file reads explicit.

Use `Refresh` to reload the selected directory level. Use `Download` to copy the selected file to the configured download root.

## Options

| Option                             | Default     | Description                                |
| ---------------------------------- | ----------- | ------------------------------------------ |
| `path`                             | none        | fsspec URL or local path to browse         |
| `-o`, `--storage-option KEY=VALUE` | none        | Backend option; may be repeated            |
| `--host`                           | `127.0.0.1` | Server host                                |
| `--port`                           | `0`         | Server port; `0` chooses an available port |
| `--page-size`                      | `256`       | Entries revealed per directory page        |
| `--preview-bytes`                  | `104857600` | Maximum bytes read for file preview        |
| `--download-root`                  | `.`         | Directory where downloads are written      |
| `--no-open`                        | off         | Do not open a browser tab                  |

## Previews

The server reads at most `--preview-bytes + 1` bytes so it can mark truncated previews. Binary files are identified without rendering bytes as text. Complete `.json` previews are pretty-printed when valid.

Metadata shown in the UI comes from fsspec listings and file info, including common created, modified, accessed, ETag, and content type fields when the backend provides them.

## Downloads

Downloads are copied through fsspec into `--download-root`. The local target path is derived from the display path while stripping protocol parts and unsafe `.` or `..` path components.
