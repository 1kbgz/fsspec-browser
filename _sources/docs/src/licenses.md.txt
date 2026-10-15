# License bundle reference

Wheels include the pnpm production dependency inventory and Cargo dependency
license texts under `fsspec_browser/licenses`. Both bundles preserve original
texts and notices.

The pnpm inventory excludes development tools. Cargo collection includes nonhost
dependencies and is not a linked-code-only inventory. Python dependencies and
separately vendored assets are outside this collection's scope.

Missing license texts fail the build. The [Cargo override reference](../../rust/LICENSES.md)
records provisional source-backed texts that require human review before shipping.
Collection does not certify license compliance.

`SKIP_HATCH_JS` skips JavaScript building and pnpm license collection. Distribution
builds require both hooks; Linux wheel containers install Node and pnpm.
