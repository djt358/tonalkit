//! Speech region, syllable nuclei and candidate syllable boundaries (spec §4.1, §7.2).
//!
//! Three steps over the tracks of `tonekit-f0`, each feeding the next:
//!
//! 1. [`speech_region`]: where the speech is, from the frame energy alone.
//! 2. [`nuclei`]: one energy peak per syllable, kept only where pYIN hears a pitch.
//! 3. [`boundaries`]: a small set of candidate syllable edges for the decoder to search.
//!
//! The decoder never assumes how many syllables were spoken. It searches segmentations over
//! [`boundaries`] only, so that list has to be generous (a missing real edge costs more than an
//! extra candidate) and is capped at `4 * nuclei + 2` so the search stays cheap.
//!
//! Frames are the 10 ms frames of the input tracks; every position here is a frame index.

#![forbid(unsafe_code)]

mod boundaries;
mod nuclei;
mod region;
mod smooth;

pub use boundaries::{boundaries, boundaries_with};
pub use nuclei::nuclei;
pub use region::{speech_region, speech_threshold, SegmentParams};
