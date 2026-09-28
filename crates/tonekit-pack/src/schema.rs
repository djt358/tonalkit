//! Serde structs mirroring the pack TOML (spec §6.2). Parsing only: meaning and validation live
//! in `load.rs`. Unknown fields are rejected everywhere so a typo cannot silently change a rule.

use std::collections::BTreeMap;

use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PackFile {
    pub pack: PackMeta,
    #[serde(rename = "tone", default)]
    pub tones: Vec<ToneDef>,
    pub tolerance: ToleranceDef,
    #[serde(default)]
    pub unvoiced_ok: Vec<UnvoicedOkDef>,
    #[serde(default)]
    pub confusions: ConfusionsDef,
    #[serde(rename = "accent", default)]
    pub accents: Vec<AccentDef>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PackMeta {
    pub lect: String,
    pub version: String,
    pub tbu: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
    pub base_accent: String,
    pub heard_threshold: f32,
    pub prior: BTreeMap<String, f32>,
}

/// A citation form: Chao knots, or the keyword `"context"`.
#[derive(Deserialize)]
#[serde(untagged)]
pub(crate) enum ChaoSpec {
    Knots(Vec<f32>),
    Keyword(String),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ToneDef {
    pub id: String,
    /// Display name only; carries no behaviour.
    #[serde(default)]
    #[allow(dead_code)]
    pub name: String,
    pub chao: ChaoSpec,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ToleranceDef {
    pub contour: f32,
    pub onset: f32,
    pub offset: f32,
    pub turning_point: f32,
}

/// Per-accent override: only the fields present replace the inherited value.
#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ToleranceOverride {
    pub contour: Option<f32>,
    pub onset: Option<f32>,
    pub offset: Option<f32>,
    pub turning_point: Option<f32>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct UnvoicedOkDef {
    pub tone: String,
    pub region: [f32; 2],
}

#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ConfusionsDef {
    #[serde(default)]
    pub pairs: Vec<[String; 2]>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct AccentDef {
    pub id: String,
    /// Display name only; carries no behaviour.
    #[serde(default)]
    #[allow(dead_code)]
    pub name: String,
    pub inherits: Option<String>,
    #[serde(default)]
    pub realize: Vec<RealizeDef>,
    #[serde(default)]
    pub tolerance: ToleranceOverride,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RealizeDef {
    pub label: String,
    pub when: WhenDef,
    pub chao: Option<Vec<f32>>,
    pub mixture: Option<Vec<MixtureDef>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct WhenDef {
    pub tone: Option<String>,
    pub prev: Option<String>,
    pub phrase_final: Option<bool>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MixtureDef {
    pub chao: Vec<f32>,
    pub weight: f32,
}
