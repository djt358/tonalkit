//! `tonekit`: the one entry point for grading lexical tone (spec §4.1).
//!
//! Analyse the audio once, then ask as many questions of the [`Analysis`] as you like:
//!
//! - [`analyze`] turns 16 kHz mono PCM into an [`Analysis`]: f0, energy, syllable nuclei,
//!   candidate boundaries, the speaker's register and any signal-quality issues.
//! - [`decode`] scores candidate readings of any syllable count against it (closed set).
//! - [`lattice`] gives per-syllable tone likelihoods with no candidates at all (open set).
//! - [`assess`] grades an intended reading: `decode` of the intended candidate and its
//!   distractors, fused with any external evidence, plus accent fit and the updated register.
//!
//! The facade holds no policy. It reports likelihoods, probabilities and diagnostics; thresholds,
//! mastery scaling and UI belong to the consumer.
//!
//! ```
//! use tonekit::{analyze, assess, AssessError, AssessRequest, LanguagePack, UtteranceAssessment};
//!
//! fn grade(
//!     pcm: &[f32],
//!     pack: &LanguagePack,
//!     request: &AssessRequest,
//! ) -> Result<UtteranceAssessment, AssessError> {
//!     let analysis = analyze(pcm, 16_000, None, &Default::default())?;
//!     assess(&analysis, pack, request)
//! }
//! ```
//!
//! Like the crates beneath it, `tonekit` uses no threads, filesystem, clock or randomness: the
//! same input always gives the same output.

#![forbid(unsafe_code)]

mod analyze;
mod assess;

pub use analyze::{analyze, AnalyzeOptions, F0Choice};
pub use assess::{assess, AssessRequest};
pub use tonekit_core::*;
pub use tonekit_decode::{decode, lattice};
pub use tonekit_pack::LanguagePack;
