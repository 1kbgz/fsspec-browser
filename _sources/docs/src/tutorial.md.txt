# Preview local data in the web browser

This tutorial creates two small data files, opens them in `fsspec-browser`, and previews
their structured contents without writing application code.

## Before you start

Install `fsspec-browser` in a Python 3.10 or newer environment:

```console
python -m pip install fsspec-browser
```

## Create files to browse

Create a directory and a CSV file:

```console
mkdir browser-demo
printf 'name,score\nAda,10\nGrace,12\n' > browser-demo/scores.csv
```

Create `browser-demo/status.json`:

```json
{
  "generated": true,
  "rows": 2
}
```

You now have one tabular file and one structured text file.

## Start the web browser

Run the browser on the directory:

```console
fsspec-browser-web browser-demo --no-open --port 8765
```

The server reports its local address:

```text
Serving fsspec-browser web UI at http://127.0.0.1:8765/
```

Open that address in a web browser. The file tree shows `scores.csv` and `status.json`.

## Preview the CSV table

Select `scores.csv`, then choose **Preview**. The preview pane shows two columns and two
rows. The preview contains Ada with score 10 and Grace with score 12.

## Preview JSON

Select `status.json`, then choose **Preview**. The preview pane shows formatted JSON with `generated` set to `true` and `rows` set to `2`.

## Stop the server

Return to the terminal and press `Ctrl-C`.

Use the
[web guide](web.md) to connect remote filesystems and control limits, or learn [why the
browser separates filesystem access from rendering](explanation.md).
