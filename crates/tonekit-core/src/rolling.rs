//! A register that follows the speaker from utterance to utterance (ruling R111).
//!
//! A learner's register moves: new speakers often start higher and with more variable pitch, and
//! settle as they gain confidence. A [`RollingRegister`] pools the speech-only voiced semitones of
//! every graded utterance (ruling R106) in a fixed grid of semitone bins, with older evidence
//! decaying ([`RollingParams::half_life_s`]) and no one utterance allowed to carry much of the
//! pool ([`RollingParams::max_share`]). Its floor, median and ceiling are the pool's weighted 5th,
//! 50th and 95th percentiles. Without decay or cap it is plain pooling of every voiced frame
//! (ruling R107). The arithmetic is `tonekit_shape::roll_register`; the facade's
//! `tonekit::roll_register` takes an analysis and its assessment.

use serde::{Deserialize, Serialize};

use crate::register::Register;

/// The lowest semitone (re 55 Hz) of the pool's grid: about 39 Hz, under pYIN's 50 Hz floor.
pub const POOL_LO_ST: f32 = -6.0;
/// The width of one bin of the pool, in semitones.
pub const POOL_BIN_ST: f32 = 0.1;
/// The number of bins: −6 to 48 semitones (39 to 880 Hz), past pYIN's 600 Hz ceiling. A pitch
/// outside the grid (only an external track can have one) counts in the nearest end bin.
pub const POOL_BINS: usize = 540;

/// A speaker's register as it stands after the utterances rolled into it, for the app to keep
/// between utterances (and sessions) in place of a plain [`Register`].
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct RollingRegister {
    /// The register to grade the next utterance with: pass it to `analyze`. Floor, median and
    /// ceiling are the pool's weighted 5th, 50th and 95th percentiles, widened while the register
    /// is cold (fewer than 30 syllables) by a margin that shrinks from the cold start's 2 st to 0,
    /// and at least 4 st wide. `n_syllables` counts every measured syllable rolled in.
    pub register: Register,
    /// The pool: per bin of [`POOL_BIN_ST`] semitones from [`POOL_LO_ST`], how many seconds of
    /// voiced speech it holds after decay. [`POOL_BINS`] long; all zero before any voiced frame.
    pub pool: Vec<f64>,
}

impl RollingRegister {
    /// Whether the pool can be rolled on: [`POOL_BINS`] weights, each finite and not negative. A
    /// stored register that fails this (corrupted, or from another grid) is started afresh.
    pub fn pool_usable(&self) -> bool {
        self.pool.len() == POOL_BINS && self.pool.iter().all(|w| w.is_finite() && *w >= 0.0)
    }
}

/// How a [`RollingRegister`] forgets. The default is the pack calibration's
/// `rolling_register`; [`RollingParams::POOLED`] is plain pooling.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct RollingParams {
    /// After this many seconds of newer voiced speech, a frame weighs half as much. `None`: no
    /// decay, every frame weighs the same forever (ruling R107's pooling).
    pub half_life_s: Option<f32>,
    /// The largest share of a full pool that one utterance may carry (0 to 1, exclusive): an
    /// utterance counts as at most `−half_life_s · log2(1 − max_share)` seconds of speech, and
    /// the decay clock advances by what it counts as, so a long shout, whisper or creaky run can
    /// neither dominate the pool nor flush it. Needs `half_life_s`. `None`: no cap.
    pub max_share: Option<f32>,
}

impl RollingParams {
    /// No decay and no cap: every voiced frame ever rolled in weighs the same (ruling R107).
    pub const POOLED: RollingParams = RollingParams {
        half_life_s: None,
        max_share: None,
    };

    /// The default (ruling R111): a half-life of 30 s of voiced speech (about 150 syllables, or
    /// 40 short phrases) and at most 3% of a full pool per utterance (1.3 s of speech).
    pub const DEFAULT: RollingParams = RollingParams {
        half_life_s: Some(30.0),
        max_share: Some(0.03),
    };

    /// Why these parameters cannot be used, if they cannot: a half-life that is not a positive
    /// finite number, a share outside (0, 1), or a share without a half-life.
    pub fn problem(&self) -> Option<String> {
        if let Some(h) = self.half_life_s {
            if !(h.is_finite() && h > 0.0) {
                return Some(format!("half_life_s must be a positive number, got {h}"));
            }
        }
        match (self.max_share, self.half_life_s) {
            (Some(c), _) if !(c > 0.0 && c < 1.0) => Some(format!(
                "max_share must be between 0 and 1 (exclusive), got {c}"
            )),
            (Some(_), None) => Some(
                "max_share needs a half_life_s: it is a share of the pool a half-life fills".into(),
            ),
            _ => None,
        }
    }
}

impl Default for RollingParams {
    fn default() -> Self {
        Self::DEFAULT
    }
}
