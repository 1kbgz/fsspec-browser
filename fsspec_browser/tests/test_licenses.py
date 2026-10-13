"""License resources must survive standard and editable wheel installation."""

import json
from importlib.metadata import distribution
from pathlib import Path


def test_installed_pnpm_license_bundle():
    dist = distribution("fsspec-browser")
    bundle = json.loads(Path(str(dist.locate_file("fsspec_browser/licenses/pnpm.json"))).read_bytes())
    assert bundle["root_name"] == "fsspec-browser"
    packages = {(library["package_name"], library["package_version"]) for library in bundle["libraries"]}
    assert len(packages) == len(bundle["libraries"])
    assert {("@pierre/trees", "1.0.0-beta.6"), ("preact", "11.0.0-beta.0")} <= packages
    for library in bundle["libraries"]:
        assert library["package_version"] and library["license"] and library["files"]
        for file in library["files"]:
            assert file["text"].strip().casefold() not in ("", "not found", "unknown")
            assert not file["path"].startswith("/")


def test_installed_cargo_license_bundle():
    dist = distribution("fsspec-browser")
    bundle = json.loads(Path(str(dist.locate_file("fsspec_browser/licenses/cargo.json"))).read_bytes())
    assert bundle["root_name"] == "fsspec_browser_py"
    packages = {(library["package_name"], library["package_version"]) for library in bundle["third_party_libraries"]}
    assert len(packages) == len(bundle["third_party_libraries"])
    assert ("fsspec_browser", dist.version) in packages
    assert {"fsspec_rs", "pyo3", "r-efi", "winapi-i686-pc-windows-gnu"} <= {name for name, _version in packages}
    for library in bundle["third_party_libraries"]:
        assert library["package_version"] and library["license"] and library["licenses"]
        for license in library["licenses"]:
            assert license["text"].strip().casefold() not in ("", "not found", "unknown")
