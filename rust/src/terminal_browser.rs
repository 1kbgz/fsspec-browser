use std::collections::{HashMap, HashSet};
use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use fsspec_rs::{FileInfo, FileSystem, FileType, FsError, FsResult, LocalFs, S3Config, S3Fs};
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Direction, Layout};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::Line;
use ratatui::widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap};
use ratatui::{Frame, Terminal};
use url::Url;

const DEFAULT_PAGE_SIZE: usize = 256;
const DEFAULT_PREVIEW_BYTES: usize = 100 * 1024 * 1024;
const PREFETCH_MARGIN: usize = 3;

struct Args {
    url: Option<String>,
    storage_options: HashMap<String, String>,
    page_size: usize,
    preview_bytes: usize,
}

#[derive(Clone, Debug)]
pub struct SessionDetails {
    pub url: String,
    pub storage_options: HashMap<String, String>,
}

impl Args {
    fn parse(mut values: impl Iterator<Item = String>) -> Result<Option<Self>, String> {
        let mut url = None;
        let mut storage_options = HashMap::new();
        let mut page_size = DEFAULT_PAGE_SIZE;
        let mut preview_bytes = DEFAULT_PREVIEW_BYTES;

        while let Some(value) = values.next() {
            match value.as_str() {
                "-h" | "--help" => return Ok(None),
                "-o" | "--storage-option" => {
                    let pair = values
                        .next()
                        .ok_or_else(|| format!("{value} requires KEY=VALUE"))?;
                    let (key, option_value) = parse_key_value(&pair)?;
                    storage_options.insert(key, option_value);
                }
                "--page-size" => {
                    let raw = values
                        .next()
                        .ok_or_else(|| "--page-size requires a value".to_string())?;
                    page_size = raw
                        .parse()
                        .map_err(|_| format!("invalid --page-size: {raw}"))?;
                }
                "--preview-bytes" => {
                    let raw = values
                        .next()
                        .ok_or_else(|| "--preview-bytes requires a value".to_string())?;
                    preview_bytes = raw
                        .parse()
                        .map_err(|_| format!("invalid --preview-bytes: {raw}"))?;
                }
                _ if value.starts_with("-o") && value.len() > 2 => {
                    let (key, option_value) = parse_key_value(&value[2..])?;
                    storage_options.insert(key, option_value);
                }
                _ if value.starts_with("--storage-option=") => {
                    let pair = value
                        .strip_prefix("--storage-option=")
                        .expect("prefix checked");
                    let (key, option_value) = parse_key_value(pair)?;
                    storage_options.insert(key, option_value);
                }
                _ if value.starts_with("--page-size=") => {
                    let raw = value.strip_prefix("--page-size=").expect("prefix checked");
                    page_size = raw
                        .parse()
                        .map_err(|_| format!("invalid --page-size: {raw}"))?;
                }
                _ if value.starts_with("--preview-bytes=") => {
                    let raw = value
                        .strip_prefix("--preview-bytes=")
                        .expect("prefix checked");
                    preview_bytes = raw
                        .parse()
                        .map_err(|_| format!("invalid --preview-bytes: {raw}"))?;
                }
                _ => {
                    if url.is_some() {
                        return Err(format!("unexpected argument: {value}"));
                    }
                    url = Some(value);
                }
            }
        }

        Ok(Some(Self {
            url,
            storage_options,
            page_size: page_size.max(1),
            preview_bytes: preview_bytes.max(1),
        }))
    }

    fn session(&self) -> Option<SessionDetails> {
        self.url.clone().map(|url| SessionDetails {
            url,
            storage_options: self.storage_options.clone(),
        })
    }
}

fn parse_key_value(pair: &str) -> Result<(String, String), String> {
    let (key, value) = pair
        .split_once('=')
        .ok_or_else(|| format!("storage option must be KEY=VALUE: {pair}"))?;
    if key.is_empty() {
        return Err(format!("storage option key is empty: {pair}"));
    }
    Ok((key.to_string(), value.to_string()))
}

fn prompt_line(prompt: &str) -> io::Result<String> {
    print!("{prompt}");
    io::stdout().flush()?;
    let mut line = String::new();
    io::stdin().read_line(&mut line)?;
    Ok(line.trim().to_string())
}

fn prompt_session(
    default_url: Option<&str>,
) -> Result<Option<SessionDetails>, Box<dyn std::error::Error>> {
    let default_url = default_url.unwrap_or(".");
    println!("fsspec-browser session");
    println!("Examples: ., /tmp, local-rs:///tmp, s3-rs://bucket/path, s3://bucket/path");
    let raw_url = prompt_line(&format!("URL/path [{default_url}]: "))?;
    let url = if raw_url.is_empty() {
        default_url.to_string()
    } else {
        raw_url
    };

    let mut storage_options = HashMap::new();
    loop {
        let option = prompt_line("storage option KEY=VALUE (empty to start): ")?;
        if option.is_empty() {
            break;
        }
        let (key, value) = parse_key_value(&option).map_err(FsError::InvalidArgument)?;
        storage_options.insert(key, value);
    }

    Ok(Some(SessionDetails {
        url,
        storage_options,
    }))
}

fn print_help() {
    println!(
        "\
fsspec-browser

Usage:
  fsspec-browser [url] [options]

URLs:
  Omit [url] to enter backend details interactively.
  Plain paths and local-rs:// URLs use the native local backend.
  s3-rs://bucket/path and s3://bucket/path use the native S3 backend.

Options:
  -o, --storage-option KEY=VALUE   Backend option. May be repeated.
      --page-size N                Entries fetched/revealed per page. Default: {DEFAULT_PAGE_SIZE}
      --preview-bytes N            Maximum file preview bytes. Default: {DEFAULT_PREVIEW_BYTES}
  -h, --help                       Show this help.

Keys:
  j/k, arrows      Move
  Enter, l         Enter selected directory
  h, Backspace     Go to parent directory
  Space            Expand/collapse selected directory
  p                Read preview bytes for selected file
  r                Refresh selected directory level
  d                Download selected file under current directory
  n                Open a new browser session
  q, Esc, Ctrl-C   Quit"
    );
}

#[derive(Clone, Debug)]
pub struct ListPage {
    pub entries: Vec<FileInfo>,
    pub has_more: bool,
}

pub trait BrowserBackend {
    fn name(&self) -> &str;
    fn auto_preview(&self) -> bool {
        false
    }
    fn list_page(&self, path: &str, offset: usize, limit: usize) -> FsResult<ListPage>;
    fn parent(&self, path: &str) -> String;
    fn preview(&self, path: &str, limit: usize) -> FsResult<Vec<u8>>;
    fn download(&self, path: &str, local: &Path) -> FsResult<()>;
    fn display_path(&self, path: &str) -> String;
}

pub type BackendResult = FsResult<(Box<dyn BrowserBackend>, String)>;

struct FsspecBackend<F: FileSystem> {
    fs: F,
    name: &'static str,
    display_protocol: &'static str,
    auto_preview: bool,
    root: Option<String>,
}

impl<F: FileSystem> FsspecBackend<F> {
    fn new(
        fs: F,
        name: &'static str,
        display_protocol: &'static str,
        auto_preview: bool,
        root: Option<String>,
    ) -> Self {
        Self {
            fs,
            name,
            display_protocol,
            auto_preview,
            root,
        }
    }

    fn display_with_root(&self, path: &str, root: &str) -> String {
        if path == root {
            return format!("{}://{root}", self.display_protocol);
        }
        if let Some(key) = path.strip_prefix(&format!("{root}/")) {
            return format!("{}://{root}/{key}", self.display_protocol);
        }
        format!("{}://{root}/{path}", self.display_protocol)
    }
}

impl<F: FileSystem> BrowserBackend for FsspecBackend<F> {
    fn name(&self) -> &str {
        self.name
    }

    fn auto_preview(&self) -> bool {
        self.auto_preview
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
        if self.root.as_deref() == Some(path) {
            return path.to_string();
        }
        let parent = self.fs.parent(path);
        if parent.is_empty() {
            self.root.clone().unwrap_or_else(|| path.to_string())
        } else {
            parent
        }
    }

    fn preview(&self, path: &str, limit: usize) -> FsResult<Vec<u8>> {
        self.fs.cat_file(path, Some(0), Some(limit as i64))
    }

    fn download(&self, path: &str, local: &Path) -> FsResult<()> {
        if let Some(parent) = local.parent() {
            fs::create_dir_all(parent)?;
        }
        let local = path_to_string(local)?;
        self.fs.get_file(path, &local)
    }

    fn display_path(&self, path: &str) -> String {
        if let Some(root) = &self.root {
            return self.display_with_root(path, root);
        }
        format!("{}://{path}", self.display_protocol)
    }
}

fn path_to_string(path: &Path) -> FsResult<String> {
    path.to_str()
        .map(ToString::to_string)
        .ok_or_else(|| FsError::Other("non-UTF-8 path".to_string()))
}

fn build_backend<F>(session: &SessionDetails, fallback: &F) -> BackendResult
where
    F: Fn(&SessionDetails, &str) -> BackendResult,
{
    if !session.url.contains("://") {
        return Ok((
            Box::new(FsspecBackend::new(
                LocalFs::new(),
                "local-rs",
                "local-rs",
                true,
                None,
            )),
            absolute_path(&session.url)?,
        ));
    }

    if let Some(path) = strip_local_url(&session.url) {
        return Ok((
            Box::new(FsspecBackend::new(
                LocalFs::new(),
                "local-rs",
                "local-rs",
                true,
                None,
            )),
            path,
        ));
    }

    let parsed =
        Url::parse(&session.url).map_err(|err| FsError::InvalidArgument(err.to_string()))?;
    match parsed.scheme() {
        "s3-rs" | "s3" => {
            let bucket = parsed
                .host_str()
                .ok_or_else(|| FsError::InvalidArgument("S3 URL must include a bucket".into()))?
                .to_string();
            let key = parsed.path().trim_start_matches('/');
            let start = if key.is_empty() {
                bucket.clone()
            } else {
                format!("{bucket}/{key}")
            };
            let mut cfg = S3Config::new(bucket.clone());
            apply_s3_options(&mut cfg, &session.storage_options);
            Ok((
                Box::new(FsspecBackend::new(
                    S3Fs::new(cfg)?,
                    "s3-rs",
                    "s3-rs",
                    false,
                    Some(bucket),
                )),
                start,
            ))
        }
        other => fallback(session, other),
    }
}

fn unsupported_backend(_session: &SessionDetails, protocol: &str) -> BackendResult {
    Err(FsError::NotSupported(format!(
        "Rust browser does not yet have a native backend for protocol: {protocol}"
    )))
}

fn strip_local_url(url: &str) -> Option<String> {
    for prefix in ["local-rs://", "file-rs://", "file://", "local://"] {
        if let Some(path) = url.strip_prefix(prefix) {
            return Some(path.to_string());
        }
    }
    None
}

fn absolute_path(path: &str) -> FsResult<String> {
    let path = shellexpand_tilde(path);
    let path = PathBuf::from(path);
    let path = if path.is_absolute() {
        path
    } else {
        env::current_dir()?.join(path)
    };
    path_to_string(&path)
}

fn shellexpand_tilde(path: &str) -> String {
    if path == "~" {
        return env::var("HOME").unwrap_or_else(|_| path.to_string());
    }
    if let Some(rest) = path.strip_prefix("~/") {
        if let Ok(home) = env::var("HOME") {
            return format!("{home}/{rest}");
        }
    }
    path.to_string()
}

fn apply_s3_options(cfg: &mut S3Config, options: &HashMap<String, String>) {
    if let Some(value) = option_value(options, &["key", "access_key_id"]) {
        cfg.access_key_id = Some(value);
    }
    if let Some(value) = option_value(options, &["secret", "secret_access_key"]) {
        cfg.secret_access_key = Some(value);
    }
    if let Some(value) = option_value(options, &["endpoint_url", "endpoint"]) {
        cfg.endpoint_url = Some(value);
    }
    if let Some(value) = option_value(options, &["token", "session_token"]) {
        cfg.session_token = Some(value);
    }
    if let Some(value) = option_value(options, &["region"]) {
        cfg.region = Some(value);
    }
    if let Some(value) = option_value(options, &["anon"]) {
        cfg.anon = matches!(value.as_str(), "1" | "true" | "True" | "yes");
    }
}

fn option_value(options: &HashMap<String, String>, keys: &[&str]) -> Option<String> {
    keys.iter()
        .find_map(|key| options.get(*key).filter(|value| !value.is_empty()).cloned())
}

#[derive(Clone, Debug)]
struct EntryNode {
    info: FileInfo,
    expanded: bool,
    children: Vec<EntryNode>,
    next_offset: usize,
    exhausted: bool,
    error: Option<String>,
}

impl EntryNode {
    fn new(info: FileInfo) -> Self {
        let exhausted = !info.is_dir();
        Self {
            info,
            expanded: false,
            children: Vec::new(),
            next_offset: 0,
            exhausted,
            error: None,
        }
    }

    fn root(path: String) -> Self {
        Self {
            info: FileInfo::directory(path),
            expanded: true,
            children: Vec::new(),
            next_offset: 0,
            exhausted: false,
            error: None,
        }
    }
}

#[derive(Clone, Debug)]
enum RowKind {
    Entry,
    LoadMore,
}

#[derive(Clone, Debug)]
struct VisibleRow {
    path: Vec<usize>,
    depth: usize,
    kind: RowKind,
}

struct BrowserApp {
    backend: Box<dyn BrowserBackend>,
    root: EntryNode,
    rows: Vec<VisibleRow>,
    selected: usize,
    page_size: usize,
    preview_bytes: usize,
    message: String,
    preview_cache: HashMap<String, Vec<String>>,
    preview_requests: HashSet<String>,
    new_session_requested: bool,
}

impl BrowserApp {
    fn new(
        backend: Box<dyn BrowserBackend>,
        start_path: String,
        page_size: usize,
        preview_bytes: usize,
    ) -> Self {
        let mut app = Self {
            backend,
            root: EntryNode::root(start_path),
            rows: Vec::new(),
            selected: 0,
            page_size,
            preview_bytes,
            message: String::new(),
            preview_cache: HashMap::new(),
            preview_requests: HashSet::new(),
            new_session_requested: false,
        };
        app.load_more_at(&[]);
        app
    }

    fn request_new_session(&mut self) {
        self.new_session_requested = true;
    }

    fn take_new_session_request(&mut self) -> bool {
        let requested = self.new_session_requested;
        self.new_session_requested = false;
        requested
    }

    fn refresh_selected_level(&mut self) {
        let Some(row) = self.rows.get(self.selected).cloned() else {
            return;
        };
        let mut refresh_path = row.path.clone();
        let selected_name = self.node_ref(&row.path).map(|node| node.info.name.clone());
        if matches!(row.kind, RowKind::Entry)
            && self
                .node_ref(&row.path)
                .map(|node| !node.info.is_dir())
                .unwrap_or(false)
        {
            refresh_path.pop();
        }
        let dir = self
            .node_ref(&refresh_path)
            .map(|node| node.info.name.clone())
            .unwrap_or_else(|| self.root.info.name.clone());
        if let Some(node) = self.node_mut(&refresh_path) {
            node.children.clear();
            node.next_offset = 0;
            node.exhausted = false;
            node.error = None;
            node.expanded = true;
        }
        self.preview_cache.clear();
        self.preview_requests.clear();
        self.load_more_at(&refresh_path);
        if let Some(name) = selected_name {
            if let Some(index) = self.row_index_by_name(&name) {
                self.selected = index;
            } else if let Some(index) = self.row_index(&refresh_path) {
                self.selected = index;
            }
        }
        self.message = format!("refreshed {}", self.backend.display_path(&dir));
    }

    fn move_selection(&mut self, delta: isize) {
        if self.rows.is_empty() {
            self.selected = 0;
            return;
        }
        let selected = self.selected as isize + delta;
        self.selected = selected.clamp(0, self.rows.len() as isize - 1) as usize;
        self.prefetch_near_selection();
    }

    fn home(&mut self) {
        self.selected = 0;
    }

    fn end(&mut self) {
        self.selected = self.rows.len().saturating_sub(1);
        self.prefetch_near_selection();
    }

    fn enter_selected(&mut self) {
        let Some(row) = self.rows.get(self.selected).cloned() else {
            return;
        };
        match row.kind {
            RowKind::LoadMore => self.load_more_at(&row.path),
            RowKind::Entry => {
                let Some(node) = self.node_ref(&row.path) else {
                    return;
                };
                if node.info.is_dir() {
                    let path = node.info.name.clone();
                    self.root = EntryNode::root(path);
                    self.selected = 0;
                    self.preview_cache.clear();
                    self.preview_requests.clear();
                    self.load_more_at(&[]);
                } else {
                    self.message = node.info.name.clone();
                }
            }
        }
    }

    fn parent(&mut self) {
        let current = self.root.info.name.clone();
        let parent = self.backend.parent(&current);
        if parent == current {
            return;
        }
        self.root = EntryNode::root(parent);
        self.selected = 0;
        self.preview_cache.clear();
        self.preview_requests.clear();
        self.load_more_at(&[]);
    }

    fn toggle_expand_selected(&mut self) {
        let Some(row) = self.rows.get(self.selected).cloned() else {
            return;
        };
        match row.kind {
            RowKind::LoadMore => self.load_more_at(&row.path),
            RowKind::Entry => {
                let mut should_load = false;
                if let Some(node) = self.node_mut(&row.path) {
                    if !node.info.is_dir() {
                        return;
                    }
                    if node.expanded {
                        node.expanded = false;
                    } else {
                        node.expanded = true;
                        should_load = node.children.is_empty() && !node.exhausted;
                    }
                }
                if should_load {
                    self.load_more_at(&row.path);
                } else {
                    self.rebuild_rows();
                }
            }
        }
    }

    fn request_preview_selected(&mut self) {
        let Some(row) = self.rows.get(self.selected).cloned() else {
            return;
        };
        if matches!(row.kind, RowKind::LoadMore) {
            self.load_more_at(&row.path);
            return;
        }
        let Some(node) = self.node_ref(&row.path) else {
            return;
        };
        if !node.info.is_file() {
            self.message = "preview unavailable for this entry".to_string();
            return;
        }
        let path = node.info.name.clone();
        self.preview_requests.insert(path.clone());
        self.message = format!("preview requested for {}", self.backend.display_path(&path));
    }

    fn download_selected(&mut self) {
        let Some(row) = self.rows.get(self.selected).cloned() else {
            return;
        };
        if matches!(row.kind, RowKind::LoadMore) {
            self.load_more_at(&row.path);
            return;
        }
        let Some(node) = self.node_ref(&row.path) else {
            return;
        };
        if !node.info.is_file() {
            self.message = "download unavailable for this entry".to_string();
            return;
        }
        let path = node.info.name.clone();
        let display_path = self.backend.display_path(&path);
        let Some(local) = download_target(&display_path) else {
            self.message = format!("download target unavailable for {display_path}");
            return;
        };
        match self.backend.download(&path, &local) {
            Ok(()) => {
                self.message = format!("downloaded {display_path} to {}", local.display());
            }
            Err(err) => {
                self.message = format!("download error: {err}");
            }
        }
    }

    fn load_more_at(&mut self, path: &[usize]) {
        let Some(node) = self.node_ref(path) else {
            return;
        };
        if !node.info.is_dir() || node.exhausted {
            self.rebuild_rows();
            return;
        }
        let dir = node.info.name.clone();
        let offset = node.next_offset;
        match self.backend.list_page(&dir, offset, self.page_size) {
            Ok(page) => {
                let count = page.entries.len();
                if let Some(node) = self.node_mut(path) {
                    for info in page.entries {
                        node.children.push(EntryNode::new(info));
                    }
                    node.next_offset += count;
                    node.exhausted = count == 0 || !page.has_more;
                    node.error = None;
                }
                self.message = format!(
                    "loaded {count} entries from {}",
                    self.backend.display_path(&dir)
                );
            }
            Err(err) => {
                if let Some(node) = self.node_mut(path) {
                    node.error = Some(err.to_string());
                    node.exhausted = true;
                }
                self.message = format!("error: {err}");
            }
        }
        self.rebuild_rows();
    }

    fn prefetch_near_selection(&mut self) {
        let end = (self.selected + PREFETCH_MARGIN + 1).min(self.rows.len());
        let rows = self.rows[self.selected..end].to_vec();
        for row in rows {
            if matches!(row.kind, RowKind::LoadMore) {
                self.load_more_at(&row.path);
                break;
            }
        }
    }

    fn rebuild_rows(&mut self) {
        let mut rows = Vec::new();
        append_rows(&self.root, &mut Vec::new(), 0, &mut rows);
        self.rows = rows;
        self.selected = self.selected.min(self.rows.len().saturating_sub(1));
    }

    fn preview_lines(&mut self) -> Vec<String> {
        let Some(row) = self.rows.get(self.selected).cloned() else {
            return vec!["empty directory".to_string()];
        };
        if matches!(row.kind, RowKind::LoadMore) {
            return vec!["loading more entries as you scroll".to_string()];
        }
        let Some(node) = self.node_ref(&row.path) else {
            return vec!["missing row".to_string()];
        };
        if node.info.is_dir() {
            let mut lines = vec![
                format!("name: {}", basename(&node.info.name)),
                format!("path: {}", self.backend.display_path(&node.info.name)),
                "type: directory".to_string(),
                format!("loaded children: {}", node.children.len()),
            ];
            lines.extend(metadata_lines(&node.info));
            if let Some(error) = &node.error {
                lines.push(format!("error: {error}"));
            }
            return lines;
        }
        if !node.info.is_file() {
            let mut lines = vec![
                format!("name: {}", basename(&node.info.name)),
                format!("path: {}", self.backend.display_path(&node.info.name)),
                format!("type: {}", node.info.file_type),
            ];
            lines.extend(metadata_lines(&node.info));
            lines.push("preview unavailable for special filesystem entries".to_string());
            return lines;
        }

        let path = node.info.name.clone();
        if !self.backend.auto_preview() && !self.preview_requests.contains(&path) {
            let mut lines = vec![
                format!("name: {}", basename(&node.info.name)),
                format!("path: {}", self.backend.display_path(&node.info.name)),
                format!("type: {}", node.info.file_type),
                format!("size: {} B", node.info.size),
            ];
            lines.extend(metadata_lines(&node.info));
            lines.push("preview disabled to avoid remote reads".to_string());
            lines.push("press p to read preview bytes".to_string());
            return lines;
        }
        if let Some(lines) = self.preview_cache.get(&path) {
            return lines.clone();
        }
        let lines = match self.backend.preview(&path, self.preview_bytes) {
            Ok(bytes) => bytes_to_preview_lines(&bytes, node.info.size > bytes.len() as u64),
            Err(err) => vec![format!("preview error: {err}")],
        };
        self.preview_cache.insert(path, lines.clone());
        lines
    }

    fn row_index(&self, path: &[usize]) -> Option<usize> {
        self.rows
            .iter()
            .position(|row| matches!(row.kind, RowKind::Entry) && row.path == path)
    }

    fn row_index_by_name(&self, name: &str) -> Option<usize> {
        self.rows.iter().position(|row| {
            matches!(row.kind, RowKind::Entry)
                && self
                    .node_ref(&row.path)
                    .map(|node| node.info.name == name)
                    .unwrap_or(false)
        })
    }

    fn node_ref(&self, path: &[usize]) -> Option<&EntryNode> {
        let mut node = &self.root;
        for idx in path {
            node = node.children.get(*idx)?;
        }
        Some(node)
    }

    fn node_mut(&mut self, path: &[usize]) -> Option<&mut EntryNode> {
        let mut node = &mut self.root;
        for idx in path {
            node = node.children.get_mut(*idx)?;
        }
        Some(node)
    }
}

fn append_rows(node: &EntryNode, path: &mut Vec<usize>, depth: usize, rows: &mut Vec<VisibleRow>) {
    for idx in 0..node.children.len() {
        path.push(idx);
        rows.push(VisibleRow {
            path: path.clone(),
            depth,
            kind: RowKind::Entry,
        });
        let child = &node.children[idx];
        if child.expanded {
            append_rows(child, path, depth + 1, rows);
            if !child.exhausted {
                rows.push(VisibleRow {
                    path: path.clone(),
                    depth: depth + 1,
                    kind: RowKind::LoadMore,
                });
            }
        }
        path.pop();
    }
    if depth == 0 && !node.exhausted {
        rows.push(VisibleRow {
            path: Vec::new(),
            depth,
            kind: RowKind::LoadMore,
        });
    }
}

fn metadata_lines(info: &FileInfo) -> Vec<String> {
    let mut lines = Vec::new();
    if let Some(created) = info.created {
        lines.push(format!("created: {}", humantime::format_rfc3339(created)));
    }
    if let Some(modified) = info.modified {
        lines.push(format!("modified: {}", humantime::format_rfc3339(modified)));
    }
    let mut extra: Vec<_> = info.extra.iter().collect();
    extra.sort_by(|(left, _), (right, _)| left.cmp(right));
    for (key, value) in extra {
        if !value.is_empty() {
            lines.push(format!("{key}: {value}"));
        }
    }
    lines
}

fn bytes_to_preview_lines(bytes: &[u8], truncated: bool) -> Vec<String> {
    if bytes.contains(&0) {
        return vec![format!("binary file, {} preview bytes", bytes.len())];
    }
    if !truncated {
        if let Ok(value) = serde_json::from_slice::<serde_json::Value>(bytes) {
            if let Ok(pretty) = serde_json::to_string_pretty(&value) {
                return pretty.lines().map(ToString::to_string).collect();
            }
        }
    }
    let text = String::from_utf8_lossy(bytes);
    let mut lines: Vec<String> = text.lines().map(ToString::to_string).collect();
    if lines.is_empty() {
        lines.push(String::new());
    }
    if truncated {
        lines.push("...".to_string());
    }
    lines
}

fn download_target(display_path: &str) -> Option<PathBuf> {
    let Ok(url) = Url::parse(display_path) else {
        let path = Path::new(display_path)
            .components()
            .filter_map(|component| match component {
                std::path::Component::Normal(part) => Some(part),
                _ => None,
            })
            .collect::<PathBuf>();
        return if path.as_os_str().is_empty() {
            None
        } else {
            Some(path)
        };
    };
    let mut path = PathBuf::new();
    if let Some(host) = url.host_str().filter(|host| !host.is_empty()) {
        path.push(host);
    }
    if let Some(segments) = url.path_segments() {
        for segment in segments {
            if !segment.is_empty() && segment != "." && segment != ".." {
                path.push(segment);
            }
        }
    }
    if path.as_os_str().is_empty() {
        None
    } else {
        Some(path)
    }
}

fn basename(path: &str) -> String {
    path.trim_end_matches(['/', '\\'])
        .rsplit(['/', '\\'])
        .next()
        .filter(|name| !name.is_empty())
        .unwrap_or(path)
        .to_string()
}

fn format_size(size: u64) -> String {
    if size == 0 {
        return String::new();
    }
    let units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let mut value = size as f64;
    for unit in units {
        if value < 1024.0 || unit == "TiB" {
            return if unit == "B" {
                format!("{size} B")
            } else {
                format!("{value:.1} {unit}")
            };
        }
        value /= 1024.0;
    }
    format!("{size} B")
}

fn row_label(app: &BrowserApp, row: &VisibleRow) -> Line<'static> {
    let indent = "  ".repeat(row.depth);
    if matches!(row.kind, RowKind::LoadMore) {
        return Line::from(format!("{indent}... load more"));
    }
    let Some(node) = app.node_ref(&row.path) else {
        return Line::from(format!("{indent}? missing"));
    };
    let marker = if node.info.is_dir() {
        if node.expanded {
            "[-]"
        } else {
            "[+]"
        }
    } else {
        "   "
    };
    let size = format_size(node.info.size);
    let label = if size.is_empty() {
        format!("{indent}{marker} {}", basename(&node.info.name))
    } else {
        format!("{indent}{marker} {}  {size}", basename(&node.info.name))
    };
    let style = if node.info.is_dir() {
        Style::default().fg(Color::Cyan)
    } else {
        Style::default()
    };
    Line::styled(label, style)
}

fn draw(frame: &mut Frame<'_>, app: &mut BrowserApp) {
    let area = frame.area();
    let vertical = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Min(3),
            Constraint::Length(1),
        ])
        .split(area);
    let body = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(48), Constraint::Percentage(52)])
        .split(vertical[1]);

    let title = format!(
        "{} | {}",
        app.backend.name(),
        app.backend.display_path(&app.root.info.name)
    );
    frame.render_widget(Paragraph::new(title), vertical[0]);

    let items: Vec<ListItem> = app
        .rows
        .iter()
        .map(|row| ListItem::new(row_label(app, row)))
        .collect();
    let mut list_state = ListState::default();
    if !items.is_empty() {
        list_state.select(Some(app.selected));
    }
    let list = List::new(items)
        .block(Block::default().title("files").borders(Borders::ALL))
        .highlight_style(Style::default().add_modifier(Modifier::REVERSED));
    frame.render_stateful_widget(list, body[0], &mut list_state);

    let preview = Paragraph::new(app.preview_lines().join("\n"))
        .block(Block::default().title("preview").borders(Borders::ALL))
        .wrap(Wrap { trim: false });
    frame.render_widget(preview, body[1]);

    let footer = format!(
        "enter open | space expand/collapse | p preview | d download | n new session | h parent | r refresh | q/ctrl-c quit | {}",
        app.message
    );
    frame.render_widget(Paragraph::new(footer), vertical[2]);
}

enum TerminalAction {
    Quit,
    NewSession,
}

fn run_terminal<F>(mut app: BrowserApp, fallback: &F) -> Result<(), Box<dyn std::error::Error>>
where
    F: Fn(&SessionDetails, &str) -> BackendResult,
{
    loop {
        enable_raw_mode()?;
        let mut stdout = io::stdout();
        execute!(stdout, EnterAlternateScreen)?;
        let backend = CrosstermBackend::new(stdout);
        let mut terminal = Terminal::new(backend)?;
        let result = run_app(&mut terminal, &mut app);
        disable_raw_mode()?;
        execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
        terminal.show_cursor()?;

        match result? {
            TerminalAction::Quit => return Ok(()),
            TerminalAction::NewSession => {
                let default_url = app.backend.display_path(&app.root.info.name);
                let Some(session) = prompt_session(Some(&default_url))? else {
                    return Ok(());
                };
                let (backend, start_path) = build_backend(&session, fallback)?;
                app = BrowserApp::new(backend, start_path, app.page_size, app.preview_bytes);
            }
        }
    }
}

fn run_app(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut BrowserApp,
) -> io::Result<TerminalAction> {
    loop {
        terminal.draw(|frame| draw(frame, app))?;
        if !event::poll(Duration::from_millis(100))? {
            continue;
        }
        let Event::Key(key) = event::read()? else {
            continue;
        };
        if key.kind != KeyEventKind::Press {
            continue;
        }
        if handle_key(app, key.code, key.modifiers) {
            return Ok(TerminalAction::Quit);
        }
        if app.take_new_session_request() {
            return Ok(TerminalAction::NewSession);
        }
    }
}

fn handle_key(app: &mut BrowserApp, code: KeyCode, modifiers: KeyModifiers) -> bool {
    match (code, modifiers) {
        (KeyCode::Char('c'), modifiers) if modifiers.contains(KeyModifiers::CONTROL) => true,
        (KeyCode::Char('q'), _) | (KeyCode::Esc, _) => true,
        (KeyCode::Up, _) | (KeyCode::Char('k'), _) => {
            app.move_selection(-1);
            false
        }
        (KeyCode::Down, _) | (KeyCode::Char('j'), _) => {
            app.move_selection(1);
            false
        }
        (KeyCode::PageUp, _) => {
            app.move_selection(-10);
            false
        }
        (KeyCode::PageDown, _) => {
            app.move_selection(10);
            false
        }
        (KeyCode::Home, _) | (KeyCode::Char('g'), _) => {
            app.home();
            false
        }
        (KeyCode::End, _) | (KeyCode::Char('G'), _) => {
            app.end();
            false
        }
        (KeyCode::Enter, _) | (KeyCode::Right, _) | (KeyCode::Char('l'), _) => {
            app.enter_selected();
            false
        }
        (KeyCode::Backspace, _) | (KeyCode::Left, _) | (KeyCode::Char('h'), _) => {
            app.parent();
            false
        }
        (KeyCode::Char(' '), _) => {
            app.toggle_expand_selected();
            false
        }
        (KeyCode::Char('p'), _) => {
            app.request_preview_selected();
            false
        }
        (KeyCode::Char('d'), _) => {
            app.download_selected();
            false
        }
        (KeyCode::Char('r'), _) => {
            app.refresh_selected_level();
            false
        }
        (KeyCode::Char('n'), _) => {
            app.request_new_session();
            false
        }
        _ => false,
    }
}

pub fn run_browser_with_fallback<F>(
    args: Vec<String>,
    fallback: F,
) -> Result<(), Box<dyn std::error::Error>>
where
    F: Fn(&SessionDetails, &str) -> BackendResult,
{
    let Some(args) = Args::parse(args.into_iter()).map_err(FsError::InvalidArgument)? else {
        print_help();
        return Ok(());
    };
    let Some(session) = (match args.session() {
        Some(session) => Some(session),
        None => prompt_session(None)?,
    }) else {
        return Ok(());
    };
    let (backend, start_path) = build_backend(&session, &fallback)?;
    let app = BrowserApp::new(backend, start_path, args.page_size, args.preview_bytes);
    run_terminal(app, &fallback)?;
    Ok(())
}

pub fn run_browser(args: Vec<String>) -> Result<(), Box<dyn std::error::Error>> {
    run_browser_with_fallback(args, unsupported_backend)
}

pub fn run_browser_from_env() -> Result<(), Box<dyn std::error::Error>> {
    run_browser(env::args().skip(1).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;

    struct MockBackend {
        pages: HashMap<(String, usize), ListPage>,
        calls: Rc<RefCell<Vec<(String, usize)>>>,
        preview_calls: Rc<RefCell<Vec<String>>>,
        auto_preview: bool,
    }

    impl BrowserBackend for MockBackend {
        fn name(&self) -> &str {
            "mock"
        }

        fn auto_preview(&self) -> bool {
            self.auto_preview
        }

        fn list_page(&self, path: &str, offset: usize, _limit: usize) -> FsResult<ListPage> {
            self.calls.borrow_mut().push((path.to_string(), offset));
            self.pages
                .get(&(path.to_string(), offset))
                .cloned()
                .ok_or_else(|| FsError::Other(format!("{path}@{offset}")))
        }

        fn parent(&self, path: &str) -> String {
            parent_path(path)
        }

        fn preview(&self, _path: &str, _limit: usize) -> FsResult<Vec<u8>> {
            self.preview_calls.borrow_mut().push(_path.to_string());
            Ok(Vec::new())
        }

        fn download(&self, _path: &str, _local: &Path) -> FsResult<()> {
            Ok(())
        }

        fn display_path(&self, path: &str) -> String {
            path.to_string()
        }
    }

    fn parent_path(path: &str) -> String {
        path.rsplit_once('/')
            .map(|(parent, _)| {
                if parent.is_empty() {
                    "/".to_string()
                } else {
                    parent.to_string()
                }
            })
            .unwrap_or_else(|| path.to_string())
    }

    fn page(entries: Vec<FileInfo>, has_more: bool) -> ListPage {
        ListPage { entries, has_more }
    }

    fn mock_app(
        pages: HashMap<(String, usize), ListPage>,
    ) -> (
        BrowserApp,
        Rc<RefCell<Vec<(String, usize)>>>,
        Rc<RefCell<Vec<String>>>,
    ) {
        let calls = Rc::new(RefCell::new(Vec::new()));
        let preview_calls = Rc::new(RefCell::new(Vec::new()));
        let backend = MockBackend {
            pages,
            calls: calls.clone(),
            preview_calls: preview_calls.clone(),
            auto_preview: false,
        };
        let app = BrowserApp::new(Box::new(backend), "/root".to_string(), 2, 16);
        (app, calls, preview_calls)
    }

    #[test]
    fn args_without_url_have_no_session() {
        let args = Args::parse(Vec::<String>::new().into_iter())
            .unwrap()
            .unwrap();

        assert!(args.session().is_none());
        assert_eq!(args.preview_bytes, 100 * 1024 * 1024);
    }

    #[test]
    fn args_with_url_have_session() {
        let args = Args::parse(vec!["s3-rs://bucket".to_string()].into_iter())
            .unwrap()
            .unwrap();
        let session = args.session().unwrap();

        assert_eq!(session.url, "s3-rs://bucket");
    }

    #[test]
    fn n_requests_new_session() {
        let mut pages = HashMap::new();
        pages.insert(("/root".to_string(), 0), page(Vec::new(), false));
        let (mut app, _calls, _) = mock_app(pages);

        assert!(!handle_key(
            &mut app,
            KeyCode::Char('n'),
            KeyModifiers::NONE
        ));
        assert!(app.take_new_session_request());
    }

    #[test]
    fn expand_is_lazy() {
        let mut pages = HashMap::new();
        pages.insert(
            ("/root".to_string(), 0),
            page(vec![FileInfo::directory("/root/dir")], false),
        );
        pages.insert(
            ("/root/dir".to_string(), 0),
            page(vec![FileInfo::file("/root/dir/file.txt", 4)], false),
        );
        let (mut app, calls, _) = mock_app(pages);

        assert_eq!(calls.borrow().as_slice(), &[("/root".to_string(), 0)]);
        app.toggle_expand_selected();

        assert_eq!(
            calls.borrow().as_slice(),
            &[("/root".to_string(), 0), ("/root/dir".to_string(), 0)]
        );
        assert_eq!(app.rows.len(), 2);
    }

    #[test]
    fn enter_replaces_current_folder() {
        let mut pages = HashMap::new();
        pages.insert(
            ("/root".to_string(), 0),
            page(vec![FileInfo::directory("/root/dir")], false),
        );
        pages.insert(
            ("/root/dir".to_string(), 0),
            page(vec![FileInfo::file("/root/dir/file.txt", 4)], false),
        );
        let (mut app, _calls, _) = mock_app(pages);

        app.enter_selected();

        assert_eq!(app.root.info.name, "/root/dir");
        assert_eq!(app.rows.len(), 1);
        assert_eq!(basename(&app.node_ref(&[0]).unwrap().info.name), "file.txt");
    }

    #[test]
    fn scrolling_near_load_more_fetches_next_page() {
        let mut pages = HashMap::new();
        pages.insert(
            ("/root".to_string(), 0),
            page(
                vec![FileInfo::file("/root/a", 1), FileInfo::file("/root/b", 1)],
                true,
            ),
        );
        pages.insert(
            ("/root".to_string(), 2),
            page(vec![FileInfo::file("/root/c", 1)], false),
        );
        let (mut app, calls, _) = mock_app(pages);

        app.move_selection(1);

        assert_eq!(
            calls.borrow().as_slice(),
            &[("/root".to_string(), 0), ("/root".to_string(), 2)]
        );
        assert_eq!(app.rows.len(), 3);
    }

    #[test]
    fn refresh_file_refreshes_parent_level() {
        let mut pages = HashMap::new();
        pages.insert(
            ("/root".to_string(), 0),
            page(vec![FileInfo::directory("/root/dir")], false),
        );
        pages.insert(
            ("/root/dir".to_string(), 0),
            page(vec![FileInfo::file("/root/dir/old.txt", 1)], false),
        );
        pages.insert(
            ("/root/dir".to_string(), 1),
            page(vec![FileInfo::file("/root/dir/new.txt", 1)], false),
        );
        let (mut app, calls, _) = mock_app(pages);

        app.toggle_expand_selected();
        app.selected = 1;
        app.refresh_selected_level();

        assert_eq!(
            calls.borrow().as_slice(),
            &[
                ("/root".to_string(), 0),
                ("/root/dir".to_string(), 0),
                ("/root/dir".to_string(), 0),
            ]
        );
        assert_eq!(app.root.info.name, "/root");
        assert!(app.node_ref(&[0]).unwrap().expanded);
    }

    #[test]
    fn special_entries_do_not_open_preview() {
        let mut pages = HashMap::new();
        pages.insert(
            ("/root".to_string(), 0),
            page(
                vec![FileInfo {
                    name: "/root/socket".to_string(),
                    size: 0,
                    file_type: FileType::Other,
                    created: None,
                    modified: None,
                    extra: HashMap::new(),
                }],
                false,
            ),
        );
        let (mut app, _calls, preview_calls) = mock_app(pages);

        let lines = app.preview_lines();

        assert_eq!(preview_calls.borrow().as_slice(), &[] as &[String]);
        assert_eq!(
            lines,
            vec![
                "name: socket".to_string(),
                "path: /root/socket".to_string(),
                "type: other".to_string(),
                "preview unavailable for special filesystem entries".to_string(),
            ]
        );
    }

    #[test]
    fn remote_preview_requires_request() {
        let mut pages = HashMap::new();
        pages.insert(
            ("/root".to_string(), 0),
            page(vec![FileInfo::file("/root/file.txt", 4)], false),
        );
        let (mut app, _calls, preview_calls) = mock_app(pages);

        let lines = app.preview_lines();

        assert_eq!(preview_calls.borrow().as_slice(), &[] as &[String]);
        assert!(lines
            .iter()
            .any(|line| line == "preview disabled to avoid remote reads"));

        app.request_preview_selected();
        let _ = app.preview_lines();

        assert_eq!(
            preview_calls.borrow().as_slice(),
            &["/root/file.txt".to_string()]
        );
    }

    #[test]
    fn download_selected_file_reports_local_target() {
        let mut pages = HashMap::new();
        pages.insert(
            ("/root".to_string(), 0),
            page(vec![FileInfo::file("/root/file.txt", 4)], false),
        );
        let (mut app, _calls, _) = mock_app(pages);

        app.download_selected();

        assert_eq!(
            app.message,
            "downloaded /root/file.txt to root/file.txt".to_string()
        );
    }

    #[test]
    fn ctrl_c_quits() {
        let mut pages = HashMap::new();
        pages.insert(("/root".to_string(), 0), page(Vec::new(), false));
        let (mut app, _calls, _) = mock_app(pages);

        assert!(handle_key(
            &mut app,
            KeyCode::Char('c'),
            KeyModifiers::CONTROL
        ));
    }

    #[test]
    fn plain_c_does_not_quit() {
        let mut pages = HashMap::new();
        pages.insert(("/root".to_string(), 0), page(Vec::new(), false));
        let (mut app, _calls, _) = mock_app(pages);

        assert!(!handle_key(
            &mut app,
            KeyCode::Char('c'),
            KeyModifiers::NONE
        ));
    }

    #[test]
    fn bytes_preview_marks_binary() {
        assert_eq!(
            bytes_to_preview_lines(b"abc\0def", false),
            vec!["binary file, 7 preview bytes"]
        );
    }

    #[test]
    fn json_preview_is_pretty_printed() {
        assert_eq!(
            bytes_to_preview_lines(br#"{"b":1,"a":[true]}"#, false),
            vec![
                "{".to_string(),
                "  \"a\": [".to_string(),
                "    true".to_string(),
                "  ],".to_string(),
                "  \"b\": 1".to_string(),
                "}".to_string(),
            ]
        );
    }

    #[test]
    fn metadata_lines_include_times_and_extras() {
        let info = FileInfo {
            name: "/root/file.txt".to_string(),
            size: 1,
            file_type: FileType::File,
            created: Some(std::time::UNIX_EPOCH),
            modified: Some(std::time::UNIX_EPOCH + Duration::from_secs(1)),
            extra: HashMap::from([("etag".to_string(), "abc".to_string())]),
        };

        assert_eq!(
            metadata_lines(&info),
            vec![
                "created: 1970-01-01T00:00:00Z".to_string(),
                "modified: 1970-01-01T00:00:01Z".to_string(),
                "etag: abc".to_string(),
            ]
        );
    }

    #[test]
    fn download_target_strips_protocol() {
        assert_eq!(
            download_target("s3-rs://bucket/some/path/file.json"),
            Some(PathBuf::from("bucket/some/path/file.json"))
        );
    }
}
