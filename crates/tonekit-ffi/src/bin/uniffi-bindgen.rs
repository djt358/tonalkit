//! `cargo run -p tonekit-ffi --features cli --bin uniffi-bindgen -- generate --library <lib> ...`:
//! UniFFI's generator, pinned to the version this crate is built with (no global install).

fn main() {
    uniffi::uniffi_bindgen_main();
}
