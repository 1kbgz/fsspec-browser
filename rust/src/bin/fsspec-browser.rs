fn main() -> Result<(), Box<dyn std::error::Error>> {
    fsspec_browser::run_browser_from_env()
}
