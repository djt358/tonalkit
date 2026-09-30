//! Evidence fusion inputs and the assembled assessment.

use serde::{Deserialize, Serialize};

use crate::ids::{AccentId, CandidateId, ToneId};
use crate::judgement::{Measured, ShapeDelta, ToneJudgement};
use crate::register::Register;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct ConfusionHit {
    pub tone: ToneId,
    pub text: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Enum))]
pub enum Evidence {
    Acoustic {
        judgement: ToneJudgement,
    },
    Transcript {
        matched_target: bool,
        confusion_hit: Option<ConfusionHit>,
    },
    /// `p_correct` is P(target tone produced) from a neural model.
    Neural {
        p_correct: f32,
        model: String,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Enum))]
pub enum EvidenceKind {
    Acoustic,
    Transcript,
    Neural,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct FusionWeights {
    pub beta0: f32,
    pub beta_acoustic: f32,
    pub beta_transcript: f32,
    pub beta_neural: f32,
    pub veto_cap: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct SyllableAssessment {
    pub expected: ToneId,
    pub p_correct: f32,
    pub distance: Option<f32>,
    pub heard: Option<ToneId>,
    pub heard_as: Option<String>,
    pub deltas: Vec<ShapeDelta>,
    pub component: Option<String>,
    pub measured: Measured,
    pub basis: Vec<EvidenceKind>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct AccentFit {
    pub accent: AccentId,
    pub llr: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct UtteranceAssessment {
    pub schema: String,
    pub intended: CandidateId,
    pub intended_rank: u32,
    /// Intended llr − max(best other candidate llr, null_llr + null_bias).
    pub margin_llr: f32,
    pub syllables: Vec<SyllableAssessment>,
    /// `None` when no syllable was measured ("tone not checked").
    pub overall: Option<f32>,
    pub accent_fit: Vec<AccentFit>,
    pub register_update: Register,
}
