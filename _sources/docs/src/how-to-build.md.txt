# How to build from source

From a source checkout, install Rust, Node.js 22, and pnpm 10.28.2. Install the
pinned Cargo license collector before building:

```console
cargo install cargo-bundle-licenses --version 4.2.0 --locked
make develop
make build
```

Keep both Hatch hooks enabled for distribution builds. `SKIP_HATCH_JS` also skips
pnpm license collection. Linux wheel containers install Node and pnpm to run that
hook.

If license collection fails, check the missing dependency against the
[Cargo override reference](../../rust/LICENSES.md). Review dependency inventories
when changing JavaScript build inputs. See [License bundle reference](licenses.md)
for included files and coverage.
