# Cargo license overrides

[license-overrides.json](license-overrides.json) supplies texts that cargo-bundle-licenses 4.2.0
does not discover for the locked dependencies. Entries match exact package name, version, and
license identifier. [license-provenance.json](license-provenance.json) records original source
locations and SHA-256 hashes.

These overrides are provisional and require human review before shipping. They do not change
the declared license choices or certify compatibility, notice sufficiency, or source-availability
requirements. Dependency updates with new missing texts fail rather than reusing another version's text.

- alloc-stdlib 0.2.4: repository LICENSE at the published crate's VCS commit.
- brotli 7.0.0: published LICENSE.BSD-3-Clause.
- flatbuffers 24.12.23: repository LICENSE at the published crate's VCS commit.
- fsspec_data 0.2.3: repository LICENSE at the published crate's VCS commit.
- fsspec_rs and fsspec_rs_bridge 0.1.5: shared repository LICENSE at the published crates' VCS commit.
- mac_address 1.2.0: published LICENSE-APACHE2.0.
- r-efi 5.3.0 and 6.0.0: complete published AUTHORS, with Apache and GNU LGPL terms appended as described below.
- ratatui-termina 0.1.0: workspace LICENSE at the published crate's VCS commit.
- termina 0.3.3: published LICENSE-MPL.
- thrift 0.17.0: repository LICENSE and NOTICE at the published crate's VCS commit.
- vtparse 0.6.2 and wezterm-input-types 0.1.0: repository LICENSE.md at each published crate's VCS commit.
- winapi-i686-pc-windows-gnu and winapi-x86_64-pc-windows-gnu 0.4.0: original repository LICENSE-MIT and LICENSE-APACHE plus published source copyright notices.

The winapi import-library crates omit license files and VCS metadata. Their published manifests,
build scripts, and library sources match commit
`9497609ef44cc9bcd16cd2411c0ee6ccaf5483aa` after newline normalization. The overrides retain the
original copyright notices from the build scripts and sources alongside the full license texts.

r-efi declares `MIT OR Apache-2.0 OR LGPL-2.1-or-later`. Each MIT entry retains the complete
original AUTHORS, including permissions, copyright holders, and contributors. Each Apache entry
appends the full Apache 2.0 text from the fsspec-rs repository LICENSE at commit
`7d85945bae87e5439a048572b3def6ff8c857587`. Each LGPL entry appends the full
[GNU LGPL 2.1 text](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt); AUTHORS retains the
"or later" permission. Those appended texts came from the previous local integration's cached
source files and were compared in full, with hashes recorded in the provenance file.

Other discovered texts remain unchanged. The source distribution includes overrides and
provenance, but excludes generated package bundles and compiled assets. Wheels contain the
collected bundle rather than the override source.
