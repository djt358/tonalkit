//! Closed-set decoding results.

use serde::{Deserialize, Serialize};

use crate::ids::CandidateId;
use crate::judgement::ToneJudgement;
use crate::shape::TbuSpan;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct SyllableFit {
    /// Where the syllable's tone was measured (ruling R55). A syllable with a nucleus reports that
    /// nucleus's tone-bearing-unit span, the one the lattice reports for it. One without (the
    /// decoder's relaxed pass: a likely miss, `Partial { [NoNucleus] }`) reports the span its path
    /// gave it, clipped to the gap between the neighbouring syllables' spans, so it can be empty.
    /// The spans of one candidate's syllables run in time order and never overlap.
    pub span: TbuSpan,
    pub judgement: ToneJudgement,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct CandidateScore {
    pub id: CandidateId,
    pub llr: f32,
    pub posterior: f32,
    pub syllables: Vec<SyllableFit>,
}

/// `candidates` sorted by llr desc; posteriors are shares of a softmax that also includes the
/// null competitor (`null_llr + null_bias`), whose share is `null_posterior`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct DecodeResult {
    pub candidates: Vec<CandidateScore>,
    pub null_llr: f32,
    pub null_posterior: f32,
}
