//! Per-syllable tone judgement and the advice attached to it.

use serde::{Deserialize, Serialize};

use crate::ids::ToneId;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Enum))]
pub enum MeasureIssue {
    Unvoiced,
    LowSnr,
    Clipped,
    TooShort,
    ColdStartRegister,
    /// The given register was not usable (non-finite or implausible levels, a median outside the
    /// floor-to-ceiling range, an inverted range, or an impossible syllable count), so the
    /// utterance was graded from a cold start instead.
    InvalidRegister,
    /// Evidence that is not a number (a non-finite shape or neural probability) was ignored.
    InvalidEvidence,
    /// The card has a syllable the utterance shows nothing for: no nucleus, pitched or unpitched,
    /// could hold it (ruling R102; it was `Unvoiced` before). Nothing about its tone was measured.
    NoNucleus,
    /// The syllable has speech energy and a vowel-like spectrum but no pitch, such as a creaky
    /// vowel (ruling R102): its tone is scored on the pack's calibrated evidence for unpitched
    /// syllables (ruling R103), not on a contour.
    Unpitched,
    /// The syllable's pitch gives way to creak: right after its last pitched frame come at least
    /// 3 frames of speech with a vowel's spectrum and no pitch (ruling R108). Its shape is
    /// measured on the pitched part, and the tail is evidence for tones that often end in creak.
    CreakyTail,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Enum))]
pub enum Measured {
    Full,
    Partial { issues: Vec<MeasureIssue> },
    NotMeasured { issue: MeasureIssue },
}

/// Advice direction ("start higher"). `amount` is in Chao units, or ms for `Turn*`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Enum))]
pub enum DeltaKind {
    StartHigher,
    StartLower,
    EndHigher,
    EndLower,
    TurnEarlier,
    TurnLater,
    WiderRange,
    NarrowerRange,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct ShapeDelta {
    pub kind: DeltaKind,
    pub amount: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct ToneJudgement {
    pub expected: ToneId,
    /// Calibrated, per inventory tone, in context.
    pub loglik: Vec<f32>,
    /// `log p(shape | target mixture) − log p(shape | background)`.
    pub llr_target: f32,
    /// To the best-matching target component (xiuzhen `contourDistance`).
    pub distance: Option<f32>,
    /// Which realisation matched, e.g. `"cmn-TW/t3-low"`.
    pub component: Option<String>,
    pub heard: Option<ToneId>,
    pub deltas: Vec<ShapeDelta>,
    pub measured: Measured,
}
