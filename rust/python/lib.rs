use std::path::Path;

use fsspec_browser_core::{
    BackendResult, BrowserBackend, ListPage, PreviewContinuation, PreviewPage, SessionDetails,
};
use fsspec_rs::{FileSystem, FileType, FsError, FsResult};
use fsspec_rs_bridge::{url_to_fs, PyFsspecFs};
use pyo3::prelude::*;

struct PythonBackend {
    fs: PyFsspecFs,
    name: String,
    root_marker: String,
    url: String,
    database: bool,
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
                database: protocol.starts_with("db+"),
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

    fn can_preview(&self, info: &fsspec_rs::FileInfo) -> bool {
        info.is_file()
            || (self.database
                && info.is_dir()
                && matches!(
                    info.extra.get("kind").map(String::as_str),
                    Some("table" | "view")
                ))
    }

    fn preview(
        &self,
        path: &str,
        continuation: Option<&PreviewContinuation>,
        limit: usize,
    ) -> FsResult<PreviewPage> {
        let offset = match continuation {
            None => 0,
            Some(PreviewContinuation::Offset(offset)) => *offset,
            Some(PreviewContinuation::Token(_)) => {
                return Err(FsError::InvalidArgument(
                    "this backend does not support token preview continuations".into(),
                ));
            }
        };
        let info = self.fs.info(path)?;
        let kind = info.extra.get("kind").map(String::as_str);
        if self.database && matches!(kind, Some("table" | "view")) {
            let data_path = format!(
                "{}.jsonl?limit=101&offset={offset}",
                path.trim_end_matches('/')
            );
            return jsonl_page(self.fs.cat_file(&data_path, None, None)?, offset);
        }
        if self.database && kind == Some("column") {
            let data_path = format!("{path}?limit=101&offset={offset}");
            return json_array_page(self.fs.cat_file(&data_path, None, None)?, offset);
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

fn jsonl_page(data: Vec<u8>, offset: usize) -> FsResult<PreviewPage> {
    let text = String::from_utf8(data).map_err(|err| FsError::Other(err.to_string()))?;
    let mut rows: Vec<&str> = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect();
    let has_more = rows.len() > 100;
    rows.truncate(100);
    let next_offset = offset + rows.len();
    Ok(PreviewPage {
        bytes: format!("[\n{}\n]", rows.join(",\n")).into_bytes(),
        continuation: has_more.then_some(PreviewContinuation::Offset(next_offset)),
    })
}

fn json_array_page(data: Vec<u8>, offset: usize) -> FsResult<PreviewPage> {
    let mut values: Vec<serde_json::Value> =
        serde_json::from_slice(&data).map_err(|err| FsError::Other(err.to_string()))?;
    let has_more = values.len() > 100;
    values.truncate(100);
    let next_offset = offset + values.len();
    Ok(PreviewPage {
        bytes: serde_json::to_vec(&values).map_err(|err| FsError::Other(err.to_string()))?,
        continuation: has_more.then_some(PreviewContinuation::Offset(next_offset)),
    })
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
