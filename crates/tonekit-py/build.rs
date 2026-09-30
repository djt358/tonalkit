//! An extension module leaves the Python C API undefined for the interpreter to provide. On Linux
//! and Windows the linker allows that; on macOS a plain `cargo build --workspace` needs
//! `-undefined dynamic_lookup`, which this adds (maturin passes the same flags itself).

fn main() {
    pyo3_build_config::add_extension_module_link_args();
}
