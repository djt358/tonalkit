//! What the caller says the speaker was aiming for.

use serde::{Deserialize, Serialize};

use crate::ids::{AccentId, CandidateId, ToneId};
use crate::style::StyleProfile;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct WeightedTone {
    pub tone: ToneId,
    pub weight: f32,
}

/// One syllable the speaker may have said. `lexical_variants` carries within-accent lexical
/// alternatives from the caller's lexicon (星期 xīngqī / xīngqí); weights sum to < 1 and the
/// main tone takes the remainder.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct ToneTarget {
    pub tone: ToneId,
    pub lexical_variants: Vec<WeightedTone>,
    pub label: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct Candidate {
    pub id: CandidateId,
    pub targets: Vec<ToneTarget>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct GradingTarget {
    pub accent: AccentId,
    pub style: Option<StyleProfile>,
    pub style_weight: f32,
}
