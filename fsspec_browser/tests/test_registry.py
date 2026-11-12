"""The terminal browser resolves URLs through the libfsspec every extension in the process shares."""

import fsspec_rs

from fsspec_browser.fsspec_browser import linked_to_libfsspec


def test_browser_shares_the_registry_with_fsspec_rs():
    assert linked_to_libfsspec() == fsspec_rs.fsspec_rs.linked_to_libfsspec()
