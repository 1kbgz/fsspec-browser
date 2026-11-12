#!/usr/bin/env bash
# delocate checks that every dependency resolves before it applies --exclude, so
# put libfsspec from the fsspec-rs wheel on its search path. The library is not
# copied into the wheel; at runtime it loads from the installed fsspec_rs package.
set -euo pipefail
archs=$1
dest=$2
wheel=$3
fsspec_rs=$(mktemp -d)
python -m pip download --quiet --no-deps --only-binary=:all: --python-version 3.11 \
    --platform macosx_11_0_arm64 --dest "$fsspec_rs" 'fsspec-rs>=0.2.1,<0.3'
python -m zipfile -e "$fsspec_rs"/fsspec_rs-*.whl "$fsspec_rs"
DYLD_LIBRARY_PATH="$fsspec_rs/fsspec_rs/lib" delocate-wheel --require-archs "$archs" --exclude libfsspec -w "$dest" -v "$wheel"
