import { FileTree } from "@pierre/trees";
import * as wasm from "../../dist/pkg/fsspec_browser";

export * as wasm from "../../dist/pkg/fsspec_browser";

type ApiEntry = {
  display_path: string;
  metadata: Record<string, string>;
  name: string;
  path: string;
  size: number | null;
  type: "directory" | "file";
};

type ApiList = {
  display_path: string;
  entries: ApiEntry[];
  has_more: boolean;
  next_offset: number | null;
  path: string;
};

type ApiPreview = {
  content: string;
  display_path: string;
  kind: "binary" | "json" | "text";
  metadata: Record<string, string>;
  path: string;
  size: number | null;
  truncated: boolean;
};

type ApiConfig = {
  active: boolean;
  display_root?: string;
  root_path?: string;
  root_url?: string;
};

type BrowserItem = ApiEntry & {
  treePath: string;
};

type LoadOptions = {
  append?: boolean;
  refresh?: boolean;
};

const itemByTreePath = new Map<string, BrowserItem>();
const childrenByParent = new Map<string, Set<string>>();
const loadedParents = new Set<string>();
const loadingParents = new Set<string>();
const nextOffsetByParent = new Map<string, number>();

let tree: FileTree | null = null;
let rootItem: BrowserItem | null = null;
let currentSelection = "";
let detachTreeInteractions: (() => void) | null = null;
let dynamicLoadTimer: number | null = null;

export const foo = () => wasm.foo();

type Theme = "dark" | "light";

const themeKey = "fsspec-browser-theme";

const storedTheme = () => {
  try {
    return window.localStorage.getItem(themeKey);
  } catch {
    return null;
  }
};

const systemTheme = (): Theme =>
  window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

const preferredTheme = (): Theme => {
  const saved = storedTheme();
  if (saved === "dark" || saved === "light") {
    return saved;
  }
  return systemTheme();
};

const updateThemeButton = (theme: Theme) => {
  const toggle = document.getElementById("theme-toggle");
  if (!(toggle instanceof HTMLButtonElement)) {
    return;
  }
  const nextTheme = theme === "dark" ? "light" : "dark";
  toggle.textContent = theme === "dark" ? "\u263e" : "\u2600";
  toggle.setAttribute("aria-label", `Switch to ${nextTheme} theme`);
  toggle.setAttribute("title", `Switch to ${nextTheme} theme`);
};

const applyTheme = (theme: Theme, persist = false) => {
  document.body.dataset.theme = theme;
  updateThemeButton(theme);
  if (!persist) {
    return;
  }
  try {
    window.localStorage.setItem(themeKey, theme);
  } catch {
    return;
  }
};

const syncSystemTheme = () => {
  if (storedTheme() === null) {
    applyTheme(systemTheme());
  }
};

const listenForSystemThemeChanges = () => {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", syncSystemTheme);
};

const currentTheme = (): Theme => {
  const theme = document.body.dataset.theme;
  if (theme === "dark" || theme === "light") {
    return theme;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
};

const formatSize = (size: number | null) => {
  if (size === null || size === undefined) {
    return "";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

const fetchJson = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, init);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload as T;
};

const parseStorageOptions = (value: string) => {
  const options: Record<string, string> = {};
  for (const line of value.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    const index = trimmed.indexOf("=");
    if (index <= 0) {
      throw new Error(`storage option must be KEY=VALUE: ${trimmed}`);
    }
    options[trimmed.slice(0, index)] = trimmed.slice(index + 1);
  }
  return options;
};

const resetBrowserState = () => {
  detachTreeInteractions?.();
  detachTreeInteractions = null;
  if (dynamicLoadTimer !== null) {
    window.clearTimeout(dynamicLoadTimer);
    dynamicLoadTimer = null;
  }
  tree?.cleanUp();
  tree = null;
  rootItem = null;
  currentSelection = "";
  itemByTreePath.clear();
  childrenByParent.clear();
  loadedParents.clear();
  loadingParents.clear();
  nextOffsetByParent.clear();
};

const queryPath = (path: string) => new URLSearchParams({ path }).toString();

const listUrl = (path: string, offset: number) => {
  const query = new URLSearchParams({ offset: String(offset), path });
  return `api/list?${query.toString()}`;
};

const parentTreePath = (treePath: string) => {
  const clean = treePath.endsWith("/") ? treePath.slice(0, -1) : treePath;
  const index = clean.lastIndexOf("/");
  return index === -1 ? "" : `${clean.slice(0, index)}/`;
};

const childTreePath = (parent: string, entry: ApiEntry) => {
  const name = entry.name.replace(/\//g, "_");
  return `${parent}${name}${entry.type === "directory" ? "/" : ""}`;
};

const removeFromState = (treePath: string) => {
  for (const child of childrenByParent.get(treePath) || []) {
    removeFromState(child);
  }
  childrenByParent.delete(treePath);
  loadedParents.delete(treePath);
  nextOffsetByParent.delete(treePath);
  itemByTreePath.delete(treePath);
};

const setStatus = (message: string) => {
  const status = document.getElementById("status");
  if (status) {
    status.textContent = message;
  }
};

const setPreview = (title: string, body: string, meta = "") => {
  const previewTitle = document.getElementById("preview-title");
  const previewMeta = document.getElementById("preview-meta");
  const previewBody = document.getElementById("preview-body");
  if (previewTitle) {
    previewTitle.textContent = title;
  }
  if (previewMeta) {
    previewMeta.textContent = meta;
  }
  if (previewBody) {
    previewBody.textContent = body;
  }
};

const setSessionFormVisible = (visible: boolean) => {
  const panel = document.getElementById("session-panel");
  if (panel) {
    panel.hidden = !visible;
  }
};

const setControlsEnabled = (enabled: boolean) => {
  for (const id of ["preview", "refresh", "download"]) {
    const button = document.getElementById(id);
    if (button instanceof HTMLButtonElement) {
      button.disabled = !enabled;
    }
  }
};

const showSessionForm = (path = "") => {
  setSessionFormVisible(true);
  setControlsEnabled(false);
  const pathInput = document.getElementById("session-path");
  if (pathInput instanceof HTMLInputElement) {
    pathInput.value = path;
    pathInput.focus();
  }
  setPreview("Session", "Enter a URL/path and optional storage options.");
  setStatus("Enter browser session details.");
};

const connectSession = async () => {
  const pathInput = document.getElementById("session-path");
  const optionsInput = document.getElementById("session-options");
  if (!(pathInput instanceof HTMLInputElement)) {
    throw new Error("missing session path input");
  }
  const path = pathInput.value.trim();
  if (!path) {
    throw new Error("URL/path is required");
  }
  const storageOptions =
    optionsInput instanceof HTMLTextAreaElement
      ? parseStorageOptions(optionsInput.value)
      : {};
  setStatus(`Opening ${path}`);
  const config = await fetchJson<ApiConfig>("api/session", {
    body: JSON.stringify({ path, storage_options: storageOptions }),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
  await startSession(config);
};

const detailLines = (item: BrowserItem) => {
  const lines = [
    `name: ${item.name}`,
    `path: ${item.display_path}`,
    `type: ${item.type}`,
  ];
  if (item.type === "file") {
    lines.push(`size: ${formatSize(item.size) || "unknown"}`);
  } else {
    const loaded = loadedParents.has(item.treePath);
    lines.push(`loaded: ${loaded ? "yes" : "no"}`);
    if (loaded) {
      lines.push(
        `loaded entries: ${childrenByParent.get(item.treePath)?.size || 0}`,
      );
      lines.push(
        `more entries: ${nextOffsetByParent.has(item.treePath) ? "yes" : "no"}`,
      );
    }
  }
  for (const [key, value] of Object.entries(item.metadata || {})) {
    lines.push(`${key}: ${value}`);
  }
  return lines.join("\n");
};

const previewMetaText = (preview: ApiPreview) => {
  const suffix = preview.truncated ? " preview truncated" : "";
  const pieces = [
    `${formatSize(preview.size)} ${preview.kind}${suffix}`.trim(),
  ];
  const metadata = preview.metadata || {};
  if (metadata.modified) {
    pieces.push(`modified ${metadata.modified}`);
  } else if (metadata.created) {
    pieces.push(`created ${metadata.created}`);
  }
  return pieces.filter(Boolean).join(" | ");
};

const showSelectionDetails = () => {
  if (!currentSelection) {
    setPreview("No selection", "Select a file or directory.");
    return;
  }
  const item = itemByTreePath.get(currentSelection);
  if (!item) {
    setPreview("Missing selection", currentSelection);
    return;
  }
  setPreview(item.name, detailLines(item), item.display_path);
};

const selectedParent = () => {
  if (!currentSelection) {
    return "";
  }
  const item = itemByTreePath.get(currentSelection);
  return item?.type === "directory"
    ? currentSelection
    : parentTreePath(currentSelection);
};

const treePathFromEvent = (event: Event) => {
  for (const target of event.composedPath()) {
    if (!(target instanceof HTMLElement)) {
      continue;
    }
    const treePath = target.dataset.itemPath;
    if (treePath !== undefined) {
      return treePath;
    }
  }
  return null;
};

const loadDirectory = async (parent: string, options: LoadOptions = {}) => {
  if (!rootItem || !tree) {
    return;
  }
  if (!options.refresh && !options.append && loadedParents.has(parent)) {
    return;
  }

  const parentItem = parent ? itemByTreePath.get(parent) : rootItem;
  if (!parentItem) {
    return;
  }

  const offset = options.append ? nextOffsetByParent.get(parent) || 0 : 0;
  setStatus(`Loading ${parentItem.display_path}`);
  const listing = await fetchJson<ApiList>(listUrl(parentItem.path, offset));
  const oldChildren = childrenByParent.get(parent) || new Set<string>();
  if (options.refresh) {
    for (const child of oldChildren) {
      if (tree.getItem(child)) {
        tree.remove(child, { recursive: true });
      }
      removeFromState(child);
    }
    oldChildren.clear();
  }

  const additions = [];
  const nextChildren = new Set<string>(options.append ? oldChildren : []);
  for (const entry of listing.entries) {
    const treePath = childTreePath(parent, entry);
    nextChildren.add(treePath);
    itemByTreePath.set(treePath, { ...entry, treePath });
    if (!tree.getItem(treePath)) {
      additions.push({ path: treePath, type: "add" as const });
    }
  }

  if (additions.length > 0) {
    tree.batch(additions);
  }
  childrenByParent.set(parent, nextChildren);
  loadedParents.add(parent);
  if (listing.has_more && listing.next_offset !== null) {
    nextOffsetByParent.set(parent, listing.next_offset);
  } else {
    nextOffsetByParent.delete(parent);
  }

  const handle = parent ? tree.getItem(parent) : null;
  if (handle?.isDirectory() && "expand" in handle) {
    handle.expand();
  }
  const more = listing.has_more ? " more available" : "";
  setStatus(
    `${listing.entries.length} items in ${listing.display_path}${more}`,
  );
};

const queueDynamicLoadCheck = () => {
  if (dynamicLoadTimer !== null) {
    return;
  }
  dynamicLoadTimer = window.setTimeout(() => {
    dynamicLoadTimer = null;
    loadMoreNearScrollEnd().catch((error: Error) => setStatus(error.message));
  }, 80);
};

const loadDirectoryOnce = async (parent: string) => {
  if (loadedParents.has(parent) || loadingParents.has(parent)) {
    return;
  }
  loadingParents.add(parent);
  try {
    await loadDirectory(parent);
  } finally {
    loadingParents.delete(parent);
  }
  if (currentSelection === parent) {
    showSelectionDetails();
  }
  queueDynamicLoadCheck();
};

const expandDirectory = (treePath: string) => {
  const handle = tree?.getItem(treePath);
  if (handle?.isDirectory() && "expand" in handle && !handle.isExpanded()) {
    handle.expand();
  }
};

const openDirectory = async (treePath: string) => {
  expandDirectory(treePath);
  await loadDirectoryOnce(treePath);
};

const syncExpandedDirectories = () => {
  for (const [treePath, item] of itemByTreePath) {
    if (
      item.type !== "directory" ||
      loadedParents.has(treePath) ||
      loadingParents.has(treePath)
    ) {
      continue;
    }
    const handle = tree?.getItem(treePath);
    if (
      handle?.isDirectory() &&
      "isExpanded" in handle &&
      handle.isExpanded()
    ) {
      loadDirectoryOnce(treePath).catch((error: Error) =>
        setStatus(error.message),
      );
    }
  }
};

const previewItem = async (treePath: string) => {
  const item = itemByTreePath.get(treePath);
  if (!item) {
    return;
  }
  if (item.type === "directory") {
    currentSelection = treePath;
    showSelectionDetails();
    setStatus(`Directory ${item.display_path}`);
    return;
  }

  setPreview(item.name, "Loading preview...", item.display_path);
  const preview = await fetchJson<ApiPreview>(
    `api/preview?${queryPath(item.path)}`,
  );
  if (preview.kind === "binary") {
    setPreview(
      item.name,
      "Binary preview unavailable.",
      previewMetaText(preview),
    );
    return;
  }
  setPreview(item.name, preview.content, previewMetaText(preview));
};

const previewSelection = async () => {
  if (!currentSelection) {
    return;
  }
  await previewItem(currentSelection);
};

const downloadSelection = async () => {
  if (!currentSelection) {
    return;
  }
  const item = itemByTreePath.get(currentSelection);
  if (!item || item.type === "directory") {
    setStatus("Select a file to download.");
    return;
  }
  const result = await fetchJson<{ local_path: string }>("api/download", {
    body: JSON.stringify({ path: item.path }),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
  setStatus(`Downloaded to ${result.local_path}`);
};

const refreshSelectedLevel = async () => {
  await loadDirectory(selectedParent(), { refresh: true });
  showSelectionDetails();
  queueDynamicLoadCheck();
};

const parentWithMoreForPath = (treePath: string) => {
  let parent = parentTreePath(treePath);
  while (true) {
    if (nextOffsetByParent.has(parent)) {
      return parent;
    }
    if (!parent) {
      return null;
    }
    parent = parentTreePath(parent);
  }
};

const lastVisibleTreePath = (scrollElement: HTMLElement) => {
  const rows = Array.from(
    scrollElement.querySelectorAll<HTMLElement>("[data-item-path]"),
  ).filter((row) => row.dataset.fileTreeStickyRow !== "true");
  return rows.length === 0
    ? null
    : rows[rows.length - 1].dataset.itemPath || null;
};

const loadMoreForParent = async (parent: string) => {
  if (!nextOffsetByParent.has(parent) || loadingParents.has(parent)) {
    return;
  }
  loadingParents.add(parent);
  try {
    await loadDirectory(parent, { append: true });
  } finally {
    loadingParents.delete(parent);
  }
  if (
    currentSelection === parent ||
    parentTreePath(currentSelection) === parent
  ) {
    showSelectionDetails();
  }
  queueDynamicLoadCheck();
};

const loadMoreNearScrollEnd = async () => {
  const host = document.querySelector("file-tree-container");
  const scrollElement = host?.shadowRoot?.querySelector<HTMLElement>(
    "[data-file-tree-virtualized-scroll='true']",
  );
  if (!scrollElement) {
    return;
  }
  const remaining =
    scrollElement.scrollHeight -
    scrollElement.scrollTop -
    scrollElement.clientHeight;
  if (remaining > 180) {
    return;
  }
  const lastPath = lastVisibleTreePath(scrollElement);
  const parent = lastPath === null ? "" : parentWithMoreForPath(lastPath);
  if (parent === null) {
    return;
  }
  await loadMoreForParent(parent);
};

const attachTreeInteractions = (treePanel: HTMLElement) => {
  detachTreeInteractions?.();
  const handleDoubleClick = (event: MouseEvent) => {
    const treePath = treePathFromEvent(event);
    if (treePath === null) {
      return;
    }
    currentSelection = treePath;
    previewItem(treePath).catch((error: Error) => setStatus(error.message));
  };
  treePanel.addEventListener("dblclick", handleDoubleClick);

  const host = document.querySelector("file-tree-container");
  const scrollElement = host?.shadowRoot?.querySelector<HTMLElement>(
    "[data-file-tree-virtualized-scroll='true']",
  );
  const handleScroll = () => queueDynamicLoadCheck();
  scrollElement?.addEventListener("scroll", handleScroll, { passive: true });

  detachTreeInteractions = () => {
    treePanel.removeEventListener("dblclick", handleDoubleClick);
    scrollElement?.removeEventListener("scroll", handleScroll);
  };
  queueDynamicLoadCheck();
};

const renderShell = () => {
  const app = document.getElementById("app");
  if (!app) {
    throw new Error("missing app mount");
  }

  app.innerHTML = `
        <section class="toolbar">
            <div class="toolbar-left">
                <strong>fsspec-browser</strong>
                <span id="root-path"></span>
            </div>
            <div class="actions">
                <button id="new-session" type="button">New Session</button>
                <button id="preview" type="button">Preview</button>
                <button id="refresh" type="button">Refresh</button>
                <button id="download" type="button">Download</button>
            </div>
            <button id="theme-toggle" class="theme-toggle" type="button"></button>
        </section>
        <section id="session-panel" class="session-panel" hidden>
            <label>
                <span>URL/path</span>
                <input id="session-path" type="text" placeholder="s3://bucket/path or /tmp" />
            </label>
            <label>
                <span>Storage options</span>
                <textarea id="session-options" rows="4" placeholder="endpoint_url=https://...\nkey=..."></textarea>
            </label>
            <button id="session-connect" type="button">Connect</button>
        </section>
        <section class="workspace">
            <div id="tree-panel"></div>
            <aside id="preview-panel">
                <div class="preview-header">
                    <strong id="preview-title">No selection</strong>
                    <span id="preview-meta"></span>
                </div>
                <pre id="preview-body">Select a file or directory.</pre>
            </aside>
        </section>
        <footer id="status"></footer>
    `;

  applyTheme(preferredTheme());
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
  });
  document.getElementById("new-session")?.addEventListener("click", () => {
    showSessionForm(rootItem?.display_path || "");
  });
  document.getElementById("session-connect")?.addEventListener("click", () => {
    connectSession().catch((error: Error) => setStatus(error.message));
  });
  document.getElementById("preview")?.addEventListener("click", () => {
    previewSelection().catch((error: Error) => setStatus(error.message));
  });
  document.getElementById("refresh")?.addEventListener("click", () => {
    refreshSelectedLevel().catch((error: Error) => setStatus(error.message));
  });
  document.getElementById("download")?.addEventListener("click", () => {
    downloadSelection().catch((error: Error) => setStatus(error.message));
  });
  window.addEventListener("keydown", (event) => {
    if (
      event.key === "r" &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey
    ) {
      event.preventDefault();
      refreshSelectedLevel().catch((error: Error) => setStatus(error.message));
    } else if (
      event.key === "p" &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey
    ) {
      event.preventDefault();
      previewSelection().catch((error: Error) => setStatus(error.message));
    } else if (
      event.key === "d" &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey
    ) {
      event.preventDefault();
      downloadSelection().catch((error: Error) => setStatus(error.message));
    }
  });
};

const startSession = async (config: ApiConfig) => {
  if (!config.active || !config.root_path || !config.display_root) {
    resetBrowserState();
    const rootPath = document.getElementById("root-path");
    if (rootPath) {
      rootPath.textContent = "No active session";
    }
    showSessionForm();
    return;
  }

  resetBrowserState();
  setSessionFormVisible(false);
  setControlsEnabled(true);
  const rootPath = document.getElementById("root-path");
  if (rootPath) {
    rootPath.textContent = config.display_root;
  }
  rootItem = {
    display_path: config.display_root,
    metadata: {},
    name: config.display_root,
    path: config.root_path,
    size: null,
    treePath: "",
    type: "directory",
  };

  const initial = await fetchJson<ApiList>(listUrl(config.root_path, 0));
  const initialPaths = [];
  const rootChildren = new Set<string>();
  for (const entry of initial.entries) {
    const treePath = childTreePath("", entry);
    itemByTreePath.set(treePath, { ...entry, treePath });
    rootChildren.add(treePath);
    initialPaths.push(treePath);
  }
  childrenByParent.set("", rootChildren);
  loadedParents.add("");
  if (initial.has_more && initial.next_offset !== null) {
    nextOffsetByParent.set("", initial.next_offset);
  }

  const treePanel = document.getElementById("tree-panel");
  if (!treePanel) {
    throw new Error("missing tree panel");
  }

  tree = new FileTree({
    flattenEmptyDirectories: false,
    initialExpansion: "closed",
    onSelectionChange: (paths) => {
      currentSelection = paths.length === 0 ? "" : paths[paths.length - 1];
      showSelectionDetails();
      const item = itemByTreePath.get(currentSelection);
      if (item?.type === "directory") {
        openDirectory(currentSelection).catch((error: Error) =>
          setStatus(error.message),
        );
      }
    },
    paths: initialPaths,
    renderRowDecoration: ({ item }) => {
      const remote = itemByTreePath.get(item.path);
      if (!remote || remote.type === "directory") {
        return null;
      }
      return { text: formatSize(remote.size) };
    },
    search: true,
    stickyFolders: true,
  });
  tree.render({ containerWrapper: treePanel });
  attachTreeInteractions(treePanel);
  tree.subscribe(syncExpandedDirectories);
  const more = initial.has_more ? " more available" : "";
  setStatus(
    `${initial.entries.length} items in ${initial.display_path}${more}`,
  );
};

const boot = async () => {
  renderShell();
  listenForSystemThemeChanges();
  const config = await fetchJson<ApiConfig>("api/config");
  await startSession(config);
};

boot().catch((error: Error) => {
  renderShell();
  setStatus(error.message);
  setPreview("Error", error.message);
});
