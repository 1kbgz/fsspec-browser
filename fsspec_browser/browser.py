"""Python entrypoint for the Rust terminal browser."""

from __future__ import annotations

import sys
from typing import Sequence

from fsspec_browser.fsspec_browser import run_browser as _run_browser


def run(argv: Sequence[str] | None = None) -> int:
    """Run the Rust browser."""
    _run_browser(list(sys.argv[1:] if argv is None else argv))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
