# API

The public Python surface is intentionally small. Most users should prefer the `fsspec-browser` and `fsspec-browser-web` command-line tools; these functions exist for embedding or testing the launchers and web server.

## Terminal Entrypoint

```{eval-rst}
.. automodule:: fsspec_browser.browser
   :members: run, main
```

## Web Entrypoint And Helpers

```{eval-rst}
.. automodule:: fsspec_browser.web
   :members: BrowserState, BrowserServer, create_state, create_server, list_entries, preview_file, download_file, run, main
```
