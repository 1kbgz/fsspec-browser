#[cfg(feature = "browser")]
mod terminal_browser;

#[cfg(feature = "browser")]
pub use terminal_browser::{run_browser, run_browser_from_env};
