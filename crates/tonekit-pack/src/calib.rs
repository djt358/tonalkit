//! Calibration parameters: the small, fitted part of a pack (`cmn.calib.json`).

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use tonekit_core::FusionWeights;

use crate::error::{invalid, PackError};

/// Closed-set and open-lattice decoding parameters (spec §7.2–7.3).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DecodeParams {
    /// Log-likelihood cost of one filler frame between syllables.
    pub filler_per_frame: f32,
    /// Log-likelihood of a syllable segment with no voiced evidence.
    pub unvoiced_syllable_llr: f32,
    /// Log-likelihood added for every nucleus that no syllable covers (an inserted syllable), on
    /// top of the per-frame filler (ruling R33).
    pub insertion_llr: f32,
    /// Added to the null competitor's log-likelihood before the softmax.
    pub null_bias: f32,
    /// σ of the log-duration prior `dur(d) = −(ln(d/r))²/(2σ²)`.
    pub dur_sigma: f32,
    /// Speaking rate `r` (seconds per syllable) used when the caller supplies none.
    pub default_rate_s: f32,
}

/// What an observation about a syllable says about its tone: per tone id, `ln P(observation |
/// tone)` at the end of a phrase and elsewhere, fitted on calibration speakers. Used for unpitched
/// syllables (ruling R103) and creaky tails (ruling R108): creak is a strong cue for tone 3 in
/// Mandarin, and the end of a full tone 4 often creaks, so these are evidence, not absence.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlaceEvidence {
    /// The phrase's last syllable (an isolated syllable included).
    pub phrase_final: BTreeMap<String, f32>,
    /// Every other syllable.
    pub other: BTreeMap<String, f32>,
}

/// Per-pack calibration. The `Default` is the seed (published tone letters; not fitted): `cmn`'s
/// shipped file is the seed plus unpitched and creaky-tail evidence fitted by `tkh fit` (rulings
/// R103, R108).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Calibration {
    /// Divides every log-likelihood before it is used.
    pub temperature: f32,
    pub fusion: FusionWeights,
    pub decode: DecodeParams,
    /// Evidence for unpitched syllables (ruling R103): `ln P(unpitched | tone)`. Without it such
    /// a syllable scores `decode.unvoiced_syllable_llr`, as a missed one does.
    pub unpitched: Option<PlaceEvidence>,
    /// Evidence for creaky tails (ruling R108): `ln P(creaky tail | tone)` for a pitched syllable
    /// whose pitch gives way to creak (`MeasureIssue::CreakyTail`), added to every tone's
    /// log-likelihood of its shape. Without it a creaky tail says nothing.
    pub creaky_tail: Option<PlaceEvidence>,
}

impl Default for Calibration {
    fn default() -> Self {
        Calibration {
            temperature: 1.0,
            fusion: FusionWeights {
                beta0: 0.0,
                beta_acoustic: 1.0,
                beta_transcript: 0.5,
                beta_neural: 0.0,
                veto_cap: 0.05,
            },
            decode: DecodeParams {
                filler_per_frame: 0.03,
                unvoiced_syllable_llr: -3.0,
                insertion_llr: -2.0,
                null_bias: -2.0,
                dur_sigma: 0.4,
                default_rate_s: 0.22,
            },
            unpitched: None,
            creaky_tail: None,
        }
    }
}

/// Strict mirror of `FusionWeights` (the core type does not reject unknown fields).
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FusionFile {
    beta0: f32,
    beta_acoustic: f32,
    beta_transcript: f32,
    beta_neural: f32,
    veto_cap: f32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CalibFile {
    temperature: f32,
    fusion: FusionFile,
    decode: DecodeParams,
    #[serde(default)]
    unpitched: Option<PlaceEvidence>,
    #[serde(default)]
    creaky_tail: Option<PlaceEvidence>,
}

impl Calibration {
    /// Parse and validate a calibration file. Every field is required except `unpitched` and
    /// `creaky_tail`, and unknown fields are rejected. Their tone ids are checked against the
    /// pack's inventory when the pack loads.
    pub(crate) fn from_json(json: &str) -> Result<Self, PackError> {
        let f: CalibFile = serde_json::from_str(json)
            .map_err(|e| PackError::Parse(format!("calibration: {e}")))?;
        let c = Calibration {
            temperature: f.temperature,
            fusion: FusionWeights {
                beta0: f.fusion.beta0,
                beta_acoustic: f.fusion.beta_acoustic,
                beta_transcript: f.fusion.beta_transcript,
                beta_neural: f.fusion.beta_neural,
                veto_cap: f.fusion.veto_cap,
            },
            decode: f.decode,
            unpitched: f.unpitched,
            creaky_tail: f.creaky_tail,
        };
        c.validate()?;
        Ok(c)
    }

    fn validate(&self) -> Result<(), PackError> {
        let d = &self.decode;
        let fu = &self.fusion;
        let finite = [
            ("fusion.beta0", fu.beta0),
            ("fusion.beta_acoustic", fu.beta_acoustic),
            ("fusion.beta_transcript", fu.beta_transcript),
            ("fusion.beta_neural", fu.beta_neural),
            ("decode.unvoiced_syllable_llr", d.unvoiced_syllable_llr),
            ("decode.insertion_llr", d.insertion_llr),
            ("decode.null_bias", d.null_bias),
        ];
        for (name, v) in finite {
            if !v.is_finite() {
                return invalid(format!("calibration {name} must be finite, got {v}"));
            }
        }
        // Both are penalties (finite, checked above): a positive value would reward skipped or
        // unmeasurable syllables.
        let penalties = [
            ("decode.unvoiced_syllable_llr", d.unvoiced_syllable_llr),
            ("decode.insertion_llr", d.insertion_llr),
        ];
        for (name, v) in penalties {
            if v > 0.0 {
                return invalid(format!(
                    "calibration {name} must be <= 0 (a positive value would reward skipped or \
                     unmeasurable syllables), got {v}"
                ));
            }
        }
        let positive = [
            ("temperature", self.temperature),
            ("decode.dur_sigma", d.dur_sigma),
            ("decode.default_rate_s", d.default_rate_s),
        ];
        for (name, v) in positive {
            if !(v.is_finite() && v > 0.0) {
                return invalid(format!("calibration {name} must be > 0, got {v}"));
            }
        }
        if !(d.filler_per_frame.is_finite() && d.filler_per_frame >= 0.0) {
            return invalid(format!(
                "calibration decode.filler_per_frame must be >= 0, got {}",
                d.filler_per_frame
            ));
        }
        if !(0.0..=1.0).contains(&fu.veto_cap) {
            return invalid(format!(
                "calibration fusion.veto_cap must be in [0, 1], got {}",
                fu.veto_cap
            ));
        }
        for (section, place, table) in self.place_tables() {
            for (tone, v) in table {
                if !(v.is_finite() && *v <= 0.0) {
                    return invalid(format!(
                        "calibration {section}.{place}.{tone} must be a log-probability \
                         (finite, <= 0), got {v}"
                    ));
                }
            }
        }
        Ok(())
    }

    /// Every table of the per-place evidence sections present, as (section, place, table).
    fn place_tables(&self) -> Vec<(&'static str, &'static str, &BTreeMap<String, f32>)> {
        [
            ("unpitched", &self.unpitched),
            ("creaky_tail", &self.creaky_tail),
        ]
        .into_iter()
        .filter_map(|(section, e)| e.as_ref().map(|e| (section, e)))
        .flat_map(|(section, e)| {
            [
                (section, "phrase_final", &e.phrase_final),
                (section, "other", &e.other),
            ]
        })
        .collect()
    }

    /// Checks that each per-place evidence table names every tone of `inventory` and nothing
    /// else.
    pub(crate) fn check_tones(&self, inventory: &[tonekit_core::ToneId]) -> Result<(), PackError> {
        let mut want: Vec<&str> = inventory.iter().map(|t| t.0.as_str()).collect();
        want.sort_unstable();
        for (section, place, table) in self.place_tables() {
            let named: Vec<&str> = table.keys().map(String::as_str).collect();
            if named != want {
                return invalid(format!(
                    "calibration {section}.{place} names tones {named:?}; the pack's are {want:?}"
                ));
            }
        }
        Ok(())
    }
}
