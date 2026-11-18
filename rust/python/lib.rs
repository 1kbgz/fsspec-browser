use std::path::Path;

mod registry;

use fsspec_browser_core::{
    BackendResult, BrowserBackend, ListPage, PreviewContinuation, PreviewPage, SessionDetails,
};
use fsspec_rs::{FileSystem, FileType, FsError, FsResult};
use fsspec_rs_bridge::PyFsspecFs;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};

struct PythonBackend {
    fs: PyFsspecFs,
    /// The Python filesystem, for the fsspec-data data-source calls in
    /// `fsspec_browser.sources`.
    py_fs: Py<PyAny>,
    name: String,
    root_marker: String,
    url: String,
}

/// Data-source previews come back as pages of at most this many rows.
const PREVIEW_ROWS: usize = 100;

impl PythonBackend {
    fn new(session: &SessionDetails, protocol: &str) -> FsResult<(Self, String)> {
        let (py_fs, start) = Python::attach(|py| {
            let kwargs = PyDict::new(py);
            for (key, value) in &session.storage_options {
                kwargs.set_item(key, value)?;
            }
            let (fs, start): (Py<PyAny>, String) = py
                .import("fsspec.core")?
                .call_method("url_to_fs", (&session.url,), Some(&kwargs))?
                .extract()?;
            PyResult::Ok((fs, start))
        })
        .map_err(python_error)?;
        let fs = Python::attach(|py| PyFsspecFs::from_py_fs(py_fs.clone_ref(py)))?;
        let root_marker = fs.root_marker().to_string();
        // A database URL names the database, not a path inside it.
        let start = if start.is_empty() || protocol.starts_with("db+") {
            root_marker.clone()
        } else {
            start
        };
        Ok((
            Self {
                fs,
                py_fs,
                name: format!("{protocol}-py"),
                root_marker,
                url: session.url.clone(),
            },
            start,
        ))
    }

    /// Calls a function of `fsspec_browser.sources` with the Python filesystem first.
    fn sources<T>(
        &self,
        function: &str,
        args: impl for<'py> FnOnce(Python<'py>) -> PyResult<Bound<'py, PyTuple>>,
        extract: impl for<'py> FnOnce(Bound<'py, PyAny>) -> PyResult<T>,
    ) -> FsResult<T> {
        Python::attach(|py| {
            let mut call_args = vec![self.py_fs.bind(py).clone()];
            call_args.extend(args(py)?.iter());
            let result = py
                .import("fsspec_browser.sources")?
                .call_method1(function, PyTuple::new(py, call_args)?)?;
            extract(result)
        })
        .map_err(python_error)
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
        entries
            .dedup_by(|left, right| left.name == right.name && left.file_type == right.file_type);
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

    /// Data sources preview tables, raw files, and metadata by their facets; other
    /// filesystems preview files.
    fn can_preview(&self, info: &fsspec_rs::FileInfo) -> bool {
        let name = info.name.clone();
        let directory = info.is_dir();
        self.sources(
            "terminal_previewable",
            |py| (name, directory).into_pyobject(py),
            |result| result.extract(),
        )
        .unwrap_or_else(|_| info.is_file())
    }

    fn preview(
        &self,
        path: &str,
        continuation: Option<&PreviewContinuation>,
        limit: usize,
    ) -> FsResult<PreviewPage> {
        let info = self.fs.info(path)?;
        if is_kafka_partition(&self.fs, &info) {
            return self.kafka_page(path, &info, continuation);
        }
        let offset = match continuation {
            None => 0,
            Some(PreviewContinuation::Offset(offset)) => *offset,
            Some(PreviewContinuation::Token(_)) => {
                return Err(FsError::InvalidArgument(
                    "this backend does not support token preview continuations".into(),
                ));
            }
        };
        let owned = path.to_string();
        let page: Option<(Vec<u8>, bool)> = self.sources(
            "terminal_page",
            |py| (owned, offset, PREVIEW_ROWS, limit).into_pyobject(py),
            |result| result.extract(),
        )?;
        if let Some((bytes, has_more)) = page {
            let rows = serde_json::from_slice::<Vec<serde_json::Value>>(&bytes)
                .map_or(0, |rows| rows.len());
            return Ok(PreviewPage {
                bytes,
                continuation: has_more.then_some(PreviewContinuation::Offset(offset + rows)),
            });
        }
        let bytes = self
            .fs
            .cat_file(path, Some(offset as i64), Some((offset + limit) as i64))?;
        let has_more = bytes.len() == limit;
        let next_offset = offset + bytes.len();
        Ok(PreviewPage {
            bytes,
            continuation: has_more.then_some(PreviewContinuation::Offset(next_offset)),
        })
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

impl PythonBackend {
    /// Up to 100 messages from a partition. Compaction leaves gaps in offsets, so the
    /// continuation token is the offset of the next message rather than a row count.
    fn kafka_page(
        &self,
        path: &str,
        info: &fsspec_rs::FileInfo,
        continuation: Option<&PreviewContinuation>,
    ) -> FsResult<PreviewPage> {
        let start = match continuation {
            None => info.extra["low"].clone(),
            Some(PreviewContinuation::Token(token)) => token.clone(),
            Some(PreviewContinuation::Offset(_)) => {
                return Err(FsError::InvalidArgument(
                    "Kafka partitions continue from tokens, not offsets".into(),
                ));
            }
        };
        let data_path = format!(
            "{}.jsonl?start={start}&limit=101",
            path.trim_end_matches('/')
        );
        let data = self.fs.cat_file(&data_path, None, None)?;
        let text = String::from_utf8(data).map_err(|err| FsError::Other(err.to_string()))?;
        let mut rows: Vec<&str> = text
            .lines()
            .filter(|line| !line.trim().is_empty())
            .collect();
        let next = match rows.get(100) {
            Some(row) => {
                let message: serde_json::Value =
                    serde_json::from_str(row).map_err(|err| FsError::Other(err.to_string()))?;
                Some(PreviewContinuation::Token(message["offset"].to_string()))
            }
            None => None,
        };
        rows.truncate(100);
        Ok(PreviewPage {
            bytes: format!("[\n{}\n]", rows.join(",\n")).into_bytes(),
            continuation: next,
        })
    }
}

/// A Kafka partition pages by message offset, since compaction leaves gaps that a
/// data source's row offsets cannot skip cheaply.
fn is_kafka_partition(fs: &PyFsspecFs, info: &fsspec_rs::FileInfo) -> bool {
    fs.source_protocol().starts_with("kafka")
        && info.is_dir()
        && info.extra.get("kind").map(String::as_str) == Some("partition")
}

fn python_error(err: PyErr) -> FsError {
    FsError::Other(err.to_string())
}

fn build_python_backend(session: &SessionDetails, protocol: &str) -> BackendResult {
    let (backend, start) = PythonBackend::new(session, protocol)?;
    Ok((Box::new(backend), start))
}

#[pyfunction]
fn run_browser(py: Python<'_>, argv: Vec<String>) -> PyResult<()> {
    let result = py.detach(|| {
        fsspec_browser_core::run_browser_with_fallback(argv, build_python_backend)
            .map_err(|err| err.to_string())
    });
    result.map_err(pyo3::exceptions::PyRuntimeError::new_err)
}

#[pymodule]
fn fsspec_browser(_py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    registry::install();
    m.add_function(wrap_pyfunction!(registry::linked_to_libfsspec, m)?)?;
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
