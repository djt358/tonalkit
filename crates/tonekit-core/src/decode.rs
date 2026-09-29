//! Closed-set decoding results.

use serde::{Deserialize, Serialize};

use crate::ids::CandidateId;
use crate::judgement::ToneJudgement;
use crate::shape::TbuSpan;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct SyllableFit {
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
