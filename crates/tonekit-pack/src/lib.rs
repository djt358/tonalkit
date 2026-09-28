//! Language packs for tonekit (spec §6): the TOML schema, loading and validation, and the
//! resolution of context-dependent expected tone shapes (accent mixtures and inheritance, lexical
//! variants, imprint style blending).
//!
//! A pack is data. `LanguagePack::from_toml` validates it completely, including that every
//! context (accent × tone × previous tone × phrase-final) resolves to an expectation, so
//! `expect_tone` and `expect` cannot hit a missing realisation on a loaded pack. Likelihoods
//! built on these expectations arrive in a later task.

#![forbid(unsafe_code)]

mod calib;
mod error;
mod expect;
mod load;
mod schema;

pub use calib::{Calibration, DecodeParams};
pub use error::PackError;
pub use expect::{Component, Expectation, TargetContext, Tolerance};

use tonekit_core::{AccentId, Lect, ToneId};

/// A validated language pack plus its calibration.
#[derive(Clone, Debug)]
pub struct LanguagePack {
    lect: Lect,
    version: String,
    /// Tone ids in `[[tone]]` file order; `prior` and `citations` are aligned with it.
    inventory: Vec<ToneId>,
    prior: Vec<f32>,
    citations: Vec<Citation>,
    base_accent: AccentId,
    heard_threshold: f32,
    unvoiced_ok: Vec<UnvoicedOk>,
    confusions: Vec<(ToneId, ToneId)>,
    /// Accents in file order.
    accents: Vec<Accent>,
    calibration: Calibration,
}

/// A tone's citation form.
#[derive(Clone, Debug)]
enum Citation {
    Knots(Vec<f32>),
    /// The tone has no fixed shape: it is realised only through `realize` rules.
    Context,
}

#[derive(Clone, Debug)]
struct UnvoicedOk {
    tone: ToneId,
    region: (f32, f32),
}

#[derive(Clone, Debug)]
struct Accent {
    id: AccentId,
    /// Index into `LanguagePack::accents`.
    inherits: Option<usize>,
    rules: Vec<Rule>,
    /// Pack default overridden along the `inherits` chain, root first.
    tolerance: Tolerance,
}

#[derive(Clone, Debug)]
struct Rule {
    label: String,
    when: When,
    realization: Realization,
}

#[derive(Clone, Debug)]
struct When {
    tone: Option<ToneId>,
    prev: Option<ToneId>,
    phrase_final: Option<bool>,
}

#[derive(Clone, Debug)]
enum Realization {
    Single(Vec<f32>),
    /// `(Chao knots, weight)`; weights sum to 1.
    Mixture(Vec<(Vec<f32>, f32)>),
}

impl LanguagePack {
    pub fn lect(&self) -> &Lect {
        &self.lect
    }

    /// The pack version from `[pack] version`.
    pub fn version(&self) -> &str {
        &self.version
    }

    /// Tone ids in `[[tone]]` file order.
    pub fn inventory(&self) -> &[ToneId] {
        &self.inventory
    }

    /// Prior probability of each tone, aligned with `inventory()` and summing to 1.
    pub fn prior(&self) -> &[f32] {
        &self.prior
    }

    pub fn base_accent(&self) -> &AccentId {
        &self.base_accent
    }

    pub fn has_accent(&self, accent: &AccentId) -> bool {
        self.accent_index(accent).is_some()
    }

    pub fn calibration(&self) -> &Calibration {
        &self.calibration
    }

    /// Minimum posterior for a tone to count as `heard`.
    pub fn heard_threshold(&self) -> f32 {
        self.heard_threshold
    }

    /// The normalised-time region `(start, end)` of `tone` where missing pitch is not penalised
    /// (T3 creak), if the pack declares one.
    pub fn unvoiced_ok(&self, tone: &ToneId) -> Option<(f32, f32)> {
        self.unvoiced_ok
            .iter()
            .find(|u| &u.tone == tone)
            .map(|u| u.region)
    }

    /// Tone pairs the pack lists as commonly confused, in file order.
    pub fn confusions(&self) -> &[(ToneId, ToneId)] {
        &self.confusions
    }

    fn accent_index(&self, accent: &AccentId) -> Option<usize> {
        self.accents.iter().position(|a| &a.id == accent)
    }

    fn tone_index(&self, tone: &ToneId) -> Option<usize> {
        self.inventory.iter().position(|t| t == tone)
    }
}
