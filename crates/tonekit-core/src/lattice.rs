//! The ensemble interface (spec §8): per-TBU likelihoods over a pack's tone inventory.

use serde::{Deserialize, Serialize};

use crate::ids::{AccentId, Lect, ToneId};
use crate::judgement::Measured;
use crate::shape::{TbuSpan, ToneShape};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LatticeTbu {
    pub span: TbuSpan,
    pub loglik: Vec<f32>,
    pub posterior: Vec<f32>,
    pub measured: Measured,
    pub shape: Option<ToneShape>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ToneLattice {
    pub schema: String,
    pub lect: Lect,
    pub accent: AccentId,
    pub inventory: Vec<ToneId>,
    pub prior: Vec<f32>,
    pub tbus: Vec<LatticeTbu>,
}
