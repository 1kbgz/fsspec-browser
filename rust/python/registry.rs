//! Points the registry the terminal browser resolves URLs with at the one every
//! extension in the process shares.

use pyo3::prelude::*;

/// Whether URLs resolve through the shared `libfsspec` rather than a registry
/// compiled into this extension.
pub const LINKED_TO_LIBFSSPEC: bool = cfg!(feature = "capi");

pub fn install() {
    #[cfg(feature = "capi")]
    fsspec_sys::use_shared_registry();
}

/// Whether this extension resolves URLs through the shared `libfsspec`.
#[pyfunction]
pub fn linked_to_libfsspec() -> bool {
    LINKED_TO_LIBFSSPEC
}
