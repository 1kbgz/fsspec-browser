# How to browse from the terminal

Install the browser:

```console
python -m pip install fsspec-browser
```

## Open a storage root

Pass a local path or S3 URL:

```console
fsspec-browser /tmp
fsspec-browser s3://bucket/path
```

Omit the path to enter connection details interactively. For other protocols,
install their fsspec backend in the same environment first:

```console
python -m pip install gcsfs
fsspec-browser gs://bucket/path
```

To connect an S3-compatible service, pass repeated storage options:

```console
fsspec-browser s3-rs://bucket/path \
  -o endpoint_url=https://s3.example.com \
  -o region=us-east-1
```

Supply credentials through your backend's configuration or storage options.
See [Command-line reference](cli.md) for accepted native S3 option names.

## Navigate and preview

Use arrows or `j`/`k` to select entries, `Enter` to enter a directory, and
`Backspace` to go to its parent. Press `p` to request a remote preview.

Press `Ctrl-A`, then `Right`, to focus the preview. Use arrows to scroll it, then
`Ctrl-A`, `Left`, to return to the browser. For Arrow IPC or Parquet tables, scroll
near the bottom to load another page.

Set preview and directory limits for the session:

```console
fsspec-browser /tmp --preview-bytes 1048576 --preview-rows 20 --page-size 500
```

## Download and refresh

Press `d` to download the selected file under the current working directory.
Press `r` to refresh the selected directory level, `n` to start another session,
and `q` to quit.

The [command-line reference](cli.md) lists all keys and exact preview limits.
