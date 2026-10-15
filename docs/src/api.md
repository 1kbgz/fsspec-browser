# Python API reference

## Terminal entry point

`run(argv=None)` passes arguments to the Rust terminal browser and returns `0` on
success. `None` uses `sys.argv[1:]`. `main(argv=None)` catches exceptions, writes
the message to standard error, and returns `1` on failure.

```{eval-rst}
.. automodule:: fsspec_browser.browser
   :members: run, main
```

## Web server and helpers

```{eval-rst}
.. automodule:: fsspec_browser.web
   :members: BrowserState, BrowserServer, create_state, create_server, list_entries, preview_file, preview_query, download_file, run, main
```

The [command-line reference](cli.md) describes session defaults and preview limits.
