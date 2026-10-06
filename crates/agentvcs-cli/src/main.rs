//! `agentvcs` — prints exactly one JSON object on stdout and exits with the
//! codes of `spec/cli/EXIT_CODES.md`. Never prompts.

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let cwd = std::env::current_dir().unwrap_or_else(|_| ".".into());
    std::process::exit(agentvcs_cli::main_with(&args, cwd))
}
