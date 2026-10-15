//! Speech region, syllable nuclei and candidate syllable boundaries (spec §4.1, §7.2).
//!
//! Three steps over the tracks of `tonekit-f0`, each feeding the next:
//!
//! 1. [`speech_region`]: where the speech is, from the frame energy alone.
//! 2. [`nuclei`]: one energy peak per syllable, kept only where pYIN hears a pitch, and at least
//!    one per long voiced run the pitch breaks around, so syllables run together with no dip
//!    still count (ruling R58).
//! 3. [`boundaries`]: a small set of candidate syllable edges for the decoder to search.
//!
//! [`extra_candidates`] adds the syllables those miss (ruling R102): loud vowel-like stretches with
//! no pitch, and a second syllable joined to a nucleus's with no dip or pitch break. The decoder
//! uses them only for a reading with more syllables than the nuclei can hold.
//!
//! The decoder never assumes how many syllables were spoken. It searches segmentations over
//! [`boundaries`] only, so that list has to be generous (a missing real edge costs more than an
//! extra candidate) and is capped at `4 * nuclei + 2` so the search stays cheap.
//!
//! Frames are the 10 ms frames of the input tracks; every position here is a frame index.

#![forbid(unsafe_code)]

mod boundaries;
mod extra;
mod nuclei;
mod region;
mod runs;
mod smooth;
mod split;
mod unpitched;

pub use boundaries::{boundaries, boundaries_with};
pub use extra::{extra_candidates, ExtraCandidates};
pub use nuclei::nuclei;
pub use region::{speech_frames, speech_region, speech_threshold, SegmentParams};
pub use unpitched::SONORANT_SHARE;
