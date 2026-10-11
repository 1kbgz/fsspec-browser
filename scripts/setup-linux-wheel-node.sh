#!/usr/bin/env bash
set -euo pipefail

# cibuildwheel invokes this inside each manylinux container as root.
case "$(uname -m)" in
    x86_64)
        arch=x64
        sha256=9aa8e9d2298ab68c600bd6fb86a6c13bce11a4eca1ba9b39d79fa021755d7c37
        ;;
    aarch64)
        arch=arm64
        sha256=1bf1eb9ee63ffc4e5d324c0b9b62cf4a289f44332dfef9607cea1a0d9596ba6f
        ;;
    *)
        printf 'Unsupported Linux wheel architecture: %s\n' "$(uname -m)" >&2
        exit 1
        ;;
esac

archive="node-v22.22.0-linux-${arch}.tar.xz"
directory=$(mktemp -d)
trap 'rm -rf "$directory"' EXIT
curl --fail --location "https://nodejs.org/dist/v22.22.0/$archive" --output "$directory/$archive"
printf '%s  %s\n' "$sha256" "$directory/$archive" | sha256sum --check -
mkdir -p /opt/fsspec-browser-node
tar -xJf "$directory/$archive" --directory /opt/fsspec-browser-node --strip-components=1
export PATH="/opt/fsspec-browser-node/bin:$PATH"
npm install --global --prefix /opt/fsspec-browser-node pnpm@10.28.2
node --version
pnpm --version