use std::path::Path;

use fsspec_browser_core::{BackendResult, BrowserBackend, ListPage, SessionDetails};
use fsspec_rs::{FileSystem, FileType, FsError, FsResult};
use fsspec_rs_bridge::{url_to_fs, PyFsspecFs};
use pyo3::prelude::*;

struct PythonBackend {
    fs: PyFsspecFs,
    name: String,
    root_marker: String,
    url: String,
}

impl PythonBackend {
    fn new(session: &SessionDetails, protocol: &str) -> FsResult<(Self, String)> {
        let (fs, start) = url_to_fs(&session.url, &session.storage_options)?;
        let root_marker = fs.root_marker().to_string();
        let start = if protocol.starts_with("db+") {
            root_marker.clone()
        } else {
            start
        };
        Ok((
            Self {
                fs,
                name: format!("{protocol}-py"),
                root_marker,
                url: session.url.clone(),
            },
            start,
        ))
    }
}

impl BrowserBackend for PythonBackend {
    fn name(&self) -> &str {
        &self.name
    }

    fn list_page(&self, path: &str, offset: usize, limit: usize) -> FsResult<ListPage> {
        let mut entries = self.fs.ls(path, true)?;
        entries.sort_by(|a, b| {
            (a.file_type != FileType::Directory)
                .cmp(&(b.file_type != FileType::Directory))
                .then_with(|| a.name.cmp(&b.name))
        });
        let total = entries.len();
        let entries = entries.into_iter().skip(offset).take(limit).collect();
        Ok(ListPage {
            entries,
            has_more: offset + limit < total,
        })
    }

    fn parent(&self, path: &str) -> String {
        parent_path(path, &self.root_marker)
    }

    fn preview(&self, path: &str, limit: usize) -> FsResult<Vec<u8>> {
        self.fs.cat_file(path, Some(0), Some(limit as i64))
    }

    fn download(&self, path: &str, local: &Path) -> FsResult<()> {
        let local = path_to_string(local)?;
        self.fs.get_file(path, &local)
    }

    fn display_path(&self, path: &str) -> String {
        if path == self.root_marker {
            self.url.clone()
        } else {
            format!("{}::{path}", self.url)
        }
    }
}

fn build_python_backend(session: &SessionDetails, protocol: &str) -> BackendResult {
    let (backend, start) = PythonBackend::new(session, protocol)?;
    Ok((Box::new(backend), start))
}

#[pyfunction]
fn run_browser(argv: Vec<String>) -> PyResult<()> {
    fsspec_browser_core::run_browser_with_fallback(argv, build_python_backend)
        .map_err(|err| pyo3::exceptions::PyRuntimeError::new_err(err.to_string()))
}

#[pymodule]
fn fsspec_browser(_py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_browser, m)?)?;
    Ok(())
}

fn path_to_string(path: &Path) -> FsResult<String> {
    path.to_str()
        .map(ToString::to_string)
        .ok_or_else(|| FsError::Other("non-UTF-8 path".to_string()))
}

fn parent_path(path: &str, root_marker: &str) -> String {
    let path = path.trim_end_matches('/');
    if path.is_empty() || path == root_marker || !path.contains('/') {
        return root_marker.to_string();
    }
    match path.rfind('/') {
        Some(0) => root_marker.to_string(),
        Some(idx) => path[..idx].to_string(),
        None => root_marker.to_string(),
    }
}
