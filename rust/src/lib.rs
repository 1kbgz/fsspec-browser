#[cfg(feature = "browser")]
mod terminal_browser;

#[cfg(feature = "browser")]
pub use terminal_browser::{
    run_browser, run_browser_from_env, run_browser_with_fallback, BackendResult, BrowserBackend,
    ListPage, PreviewContent, PreviewContinuation, PreviewDataPage, PreviewPage, SessionDetails,
};

#[cfg(test)]
mod tests {
    #[test]
    fn package_name_matches_crate() {
        assert_eq!(env!("CARGO_PKG_NAME"), "fsspec_browser");
    }

    #[test]
    fn package_description_matches_scope() {
        let description = env!("CARGO_PKG_DESCRIPTION");

        assert!(description.contains("fsspec"));
        assert!(description.contains("browser"));
    }
}
