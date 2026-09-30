//! `cargo run -p tonekit-ffi --features cli --bin uniffi-bindgen-swift -- <lib> <out-dir> ...`:
//! UniFFI's Swift-specific generator (Swift sources, C headers and a module map for an
//! XCFramework), pinned to the version this crate is built with.

fn main() {
    uniffi::uniffi_bindgen_swift();
}
