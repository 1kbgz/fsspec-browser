use pyo3::prelude::*;

#[pyfunction]
fn run_browser(argv: Vec<String>) -> PyResult<()> {
    fsspec_browser_core::run_browser(argv)
        .map_err(|err| pyo3::exceptions::PyRuntimeError::new_err(err.to_string()))
}

#[pymodule]
fn fsspec_browser(_py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_browser, m)?)?;
    Ok(())
}
