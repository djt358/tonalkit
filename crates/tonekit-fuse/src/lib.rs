//! Evidence fusion and assessment assembly (spec §7.4).
//!
//! [`fuse_syllable`] turns one acoustic [`SyllableFit`](tonekit_core::SyllableFit) plus any external
//! evidence into a calibrated per-syllable probability. [`assemble`] does that for every syllable of
//! the intended candidate and adds the utterance-level rank, margin and `overall`.

#![forbid(unsafe_code)]

mod assemble;
mod syllable;

pub use assemble::assemble;
pub use syllable::fuse_syllable;
