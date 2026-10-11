//! `LanguagePack::from_toml`: parse, validate (spec §6.2) and enumerate every context.

use std::collections::{BTreeMap, BTreeSet};

use tonekit_core::{AccentId, Lect, ToneId};

use crate::calib::Calibration;
use crate::error::{invalid, PackError};
use crate::expect::{TargetContext, Tolerance};
use crate::schema::{
    AccentDef, ChaoSpec, PackFile, RealizeDef, ToleranceDef, ToleranceOverride, UnvoicedOkDef,
};
use crate::{Accent, Citation, LanguagePack, Realization, Rule, UnvoicedOk, When};

/// Capabilities that core implements in P0. Anything else needs code, not data.
const KNOWN_CAPABILITIES: &[&str] = &["register"];
/// The only time-bearing unit the P0 segmenter knows.
const KNOWN_TBU: &str = "syllable";
/// A prior may be off by this much before normalising; beyond it the author made a mistake.
const PRIOR_SUM_SLACK: f32 = 0.01;
/// Mixture weights must sum to 1 within this.
const MIXTURE_SUM_SLACK: f32 = 1e-3;

impl LanguagePack {
    /// Parse and fully validate a pack. `calib_json` of `None` uses the seed `Calibration`.
    pub fn from_toml(pack_toml: &str, calib_json: Option<&str>) -> Result<Self, PackError> {
        let file: PackFile =
            toml::from_str(pack_toml).map_err(|e| PackError::Parse(e.to_string()))?;
        let calibration = match calib_json {
            Some(json) => Calibration::from_json(json)?,
            None => Calibration::default(),
        };

        let meta = &file.pack;
        non_empty("pack.lect", &meta.lect)?;
        non_empty("pack.version", &meta.version)?;
        if meta.tbu != KNOWN_TBU {
            return invalid(format!(
                "pack.tbu {:?} is not supported (only {KNOWN_TBU:?})",
                meta.tbu
            ));
        }
        for cap in &meta.capabilities {
            if !KNOWN_CAPABILITIES.contains(&cap.as_str()) {
                return invalid(format!(
                    "unknown capability {cap:?} (known: {KNOWN_CAPABILITIES:?})"
                ));
            }
        }
        if !(0.0..=1.0).contains(&meta.heard_threshold) {
            return invalid(format!(
                "pack.heard_threshold must be in [0, 1], got {}",
                meta.heard_threshold
            ));
        }

        let (inventory, citations) = build_inventory(&file)?;
        calibration.check_tones(&inventory)?;
        let prior = build_prior(&file, &inventory)?;
        let pack_tolerance = tolerance_from(&file.tolerance)?;
        let unvoiced_ok = build_unvoiced_ok(&file.unvoiced_ok, &inventory)?;
        let confusions = build_confusions(&file, &inventory)?;
        let accents = build_accents(&file, &inventory, pack_tolerance)?;

        let base_accent = AccentId(meta.base_accent.clone());
        if !accents.iter().any(|a| a.id == base_accent) {
            return invalid(format!(
                "pack.base_accent {:?} is not a declared accent",
                meta.base_accent
            ));
        }

        let pack = LanguagePack {
            lect: Lect(meta.lect.clone()),
            version: meta.version.clone(),
            inventory,
            prior,
            citations,
            base_accent,
            heard_threshold: meta.heard_threshold,
            unvoiced_ok,
            confusions,
            accents,
            calibration,
        };
        pack.check_every_context_resolves()?;
        Ok(pack)
    }

    /// Enumerate accent × tone × prev ∈ {None} ∪ inventory × phrase_final and require a
    /// realisation for each, so a loaded pack never fails to resolve a valid context.
    fn check_every_context_resolves(&self) -> Result<(), PackError> {
        let prevs: Vec<Option<&ToneId>> = std::iter::once(None)
            .chain(self.inventory.iter().map(Some))
            .collect();
        for accent in 0..self.accents.len() {
            for tone in 0..self.inventory.len() {
                for prev in &prevs {
                    for phrase_final in [false, true] {
                        let ctx = TargetContext {
                            index: 0,
                            count: 1,
                            prev: prev.cloned(),
                            phrase_final,
                        };
                        self.resolve(accent, tone, &ctx)?;
                    }
                }
            }
        }
        Ok(())
    }
}

fn non_empty(what: &str, s: &str) -> Result<(), PackError> {
    if s.trim().is_empty() {
        return invalid(format!("{what} must not be empty"));
    }
    Ok(())
}

fn finite_knots(what: &str, knots: &[f32]) -> Result<(), PackError> {
    if knots.is_empty() {
        return invalid(format!("{what}: chao must have at least one knot"));
    }
    if let Some(bad) = knots.iter().find(|k| !k.is_finite()) {
        return invalid(format!("{what}: chao knot {bad} is not finite"));
    }
    Ok(())
}

fn build_inventory(file: &PackFile) -> Result<(Vec<ToneId>, Vec<Citation>), PackError> {
    if file.tones.is_empty() {
        return invalid("pack declares no [[tone]]");
    }
    let mut seen = BTreeSet::new();
    let mut inventory = Vec::new();
    let mut citations = Vec::new();
    for t in &file.tones {
        non_empty("tone id", &t.id)?;
        if !seen.insert(t.id.as_str()) {
            return invalid(format!("duplicate tone id {:?}", t.id));
        }
        let what = format!("tone {:?}", t.id);
        let citation = match &t.chao {
            ChaoSpec::Knots(knots) => {
                finite_knots(&what, knots)?;
                Citation::Knots(knots.clone())
            }
            ChaoSpec::Keyword(k) if k == "context" => Citation::Context,
            ChaoSpec::Keyword(k) => {
                return invalid(format!(
                    "{what}: chao must be an array of knots or \"context\", got {k:?}"
                ))
            }
        };
        inventory.push(ToneId(t.id.clone()));
        citations.push(citation);
    }
    Ok((inventory, citations))
}

/// Keys must equal the inventory ids; values are normalised to sum 1.
fn build_prior(file: &PackFile, inventory: &[ToneId]) -> Result<Vec<f32>, PackError> {
    let prior = &file.pack.prior;
    let ids: BTreeSet<&str> = inventory.iter().map(|t| t.0.as_str()).collect();
    if let Some(extra) = prior.keys().find(|k| !ids.contains(k.as_str())) {
        return invalid(format!(
            "pack.prior has key {extra:?}, which is not a tone id"
        ));
    }
    let mut values = Vec::with_capacity(inventory.len());
    for id in inventory {
        let Some(&v) = prior.get(&id.0) else {
            return invalid(format!("pack.prior is missing tone {:?}", id.0));
        };
        if !(v.is_finite() && v > 0.0) {
            return invalid(format!(
                "pack.prior for tone {:?} must be > 0, got {v}",
                id.0
            ));
        }
        values.push(v);
    }
    let sum: f32 = values.iter().sum();
    if (sum - 1.0).abs() > PRIOR_SUM_SLACK {
        return invalid(format!(
            "pack.prior sums to {sum}, expected 1 (±{PRIOR_SUM_SLACK})"
        ));
    }
    Ok(values.into_iter().map(|v| v / sum).collect())
}

fn positive(what: &str, v: f32) -> Result<f32, PackError> {
    if v.is_finite() && v > 0.0 {
        Ok(v)
    } else {
        invalid(format!("{what} must be > 0, got {v}"))
    }
}

fn tolerance_from(def: &ToleranceDef) -> Result<Tolerance, PackError> {
    Ok(Tolerance {
        contour: positive("tolerance.contour", def.contour)?,
        onset: positive("tolerance.onset", def.onset)?,
        offset: positive("tolerance.offset", def.offset)?,
        turning_point: positive("tolerance.turning_point", def.turning_point)?,
    })
}

/// Replace only the fields `ov` sets.
fn override_tolerance(
    base: Tolerance,
    ov: &ToleranceOverride,
    accent: &str,
) -> Result<Tolerance, PackError> {
    let pick = |name: &str, current: f32, new: Option<f32>| match new {
        Some(v) => positive(&format!("accent {accent:?} tolerance.{name}"), v),
        None => Ok(current),
    };
    Ok(Tolerance {
        contour: pick("contour", base.contour, ov.contour)?,
        onset: pick("onset", base.onset, ov.onset)?,
        offset: pick("offset", base.offset, ov.offset)?,
        turning_point: pick("turning_point", base.turning_point, ov.turning_point)?,
    })
}

fn tone_known(inventory: &[ToneId], what: &str, id: &str) -> Result<ToneId, PackError> {
    let t = ToneId(id.to_string());
    if inventory.contains(&t) {
        Ok(t)
    } else {
        invalid(format!("{what} references unknown tone {id:?}"))
    }
}

fn build_unvoiced_ok(
    defs: &[UnvoicedOkDef],
    inventory: &[ToneId],
) -> Result<Vec<UnvoicedOk>, PackError> {
    let mut out: Vec<UnvoicedOk> = Vec::new();
    for d in defs {
        let tone = tone_known(inventory, "[[unvoiced_ok]]", &d.tone)?;
        if out.iter().any(|u| u.tone == tone) {
            return invalid(format!(
                "[[unvoiced_ok]] declared twice for tone {:?}",
                d.tone
            ));
        }
        let [lo, hi] = d.region;
        if !(lo.is_finite() && hi.is_finite() && 0.0 <= lo && lo < hi && hi <= 1.0) {
            return invalid(format!(
                "[[unvoiced_ok]] region for tone {:?} must satisfy 0 <= start < end <= 1, got [{lo}, {hi}]",
                d.tone
            ));
        }
        out.push(UnvoicedOk {
            tone,
            region: (lo, hi),
        });
    }
    Ok(out)
}

fn build_confusions(
    file: &PackFile,
    inventory: &[ToneId],
) -> Result<Vec<(ToneId, ToneId)>, PackError> {
    let mut out = Vec::new();
    for [a, b] in &file.confusions.pairs {
        let ta = tone_known(inventory, "[confusions]", a)?;
        let tb = tone_known(inventory, "[confusions]", b)?;
        if ta == tb {
            return invalid(format!("[confusions] pair [{a:?}, {b:?}] repeats a tone"));
        }
        out.push((ta, tb));
    }
    Ok(out)
}

fn build_accents(
    file: &PackFile,
    inventory: &[ToneId],
    pack_tolerance: Tolerance,
) -> Result<Vec<Accent>, PackError> {
    if file.accents.is_empty() {
        return invalid("pack declares no [[accent]]");
    }
    // Ids first, so `inherits` may refer forwards.
    let mut index: BTreeMap<&str, usize> = BTreeMap::new();
    for (i, a) in file.accents.iter().enumerate() {
        non_empty("accent id", &a.id)?;
        if index.insert(a.id.as_str(), i).is_some() {
            return invalid(format!("duplicate accent id {:?}", a.id));
        }
    }
    let mut parents: Vec<Option<usize>> = Vec::with_capacity(file.accents.len());
    for a in &file.accents {
        parents.push(match &a.inherits {
            None => None,
            Some(p) => match index.get(p.as_str()) {
                Some(&i) => Some(i),
                None => return invalid(format!("accent {:?} inherits unknown accent {p:?}", a.id)),
            },
        });
    }
    // Every chain must reach a root within `len` hops.
    for (i, a) in file.accents.iter().enumerate() {
        let mut cur = parents[i];
        let mut hops = 0;
        while let Some(c) = cur {
            hops += 1;
            if hops > file.accents.len() {
                return invalid(format!("accent {:?} is part of an inherits cycle", a.id));
            }
            cur = parents[c];
        }
    }

    let mut accents = Vec::with_capacity(file.accents.len());
    for (i, a) in file.accents.iter().enumerate() {
        // Root first: pack default, then each ancestor's overrides, then this accent's own.
        let mut chain = vec![i];
        let mut cur = parents[i];
        while let Some(c) = cur {
            chain.push(c);
            cur = parents[c];
        }
        let mut tolerance = pack_tolerance;
        for &c in chain.iter().rev() {
            let def = &file.accents[c];
            tolerance = override_tolerance(tolerance, &def.tolerance, &def.id)?;
        }
        accents.push(Accent {
            id: AccentId(a.id.clone()),
            inherits: parents[i],
            rules: build_rules(a, inventory)?,
            tolerance,
        });
    }
    Ok(accents)
}

fn build_rules(accent: &AccentDef, inventory: &[ToneId]) -> Result<Vec<Rule>, PackError> {
    let mut labels = BTreeSet::new();
    let mut rules = Vec::with_capacity(accent.realize.len());
    for r in &accent.realize {
        let what = format!("accent {:?} rule {:?}", accent.id, r.label);
        non_empty(&format!("accent {:?} rule label", accent.id), &r.label)?;
        if r.label.contains('#') {
            return invalid(format!("{what}: label must not contain '#'"));
        }
        if !labels.insert(r.label.as_str()) {
            return invalid(format!("{what}: duplicate label in this accent"));
        }
        rules.push(Rule {
            label: r.label.clone(),
            when: build_when(r, inventory, &what)?,
            realization: build_realization(r, &what)?,
        });
    }
    Ok(rules)
}

fn build_when(r: &RealizeDef, inventory: &[ToneId], what: &str) -> Result<When, PackError> {
    let w = &r.when;
    if w.tone.is_none() && w.prev.is_none() && w.phrase_final.is_none() {
        return invalid(format!("{what}: `when` must have at least one key"));
    }
    let known = |key: &str, id: &Option<String>| match id {
        Some(id) => tone_known(inventory, &format!("{what} when.{key}"), id).map(Some),
        None => Ok(None),
    };
    Ok(When {
        tone: known("tone", &w.tone)?,
        prev: known("prev", &w.prev)?,
        phrase_final: w.phrase_final,
    })
}

fn build_realization(r: &RealizeDef, what: &str) -> Result<Realization, PackError> {
    match (&r.chao, &r.mixture) {
        (Some(knots), None) => {
            finite_knots(what, knots)?;
            Ok(Realization::Single(knots.clone()))
        }
        (None, Some(parts)) => {
            if parts.is_empty() {
                return invalid(format!("{what}: mixture must not be empty"));
            }
            let mut sum = 0.0f32;
            for (i, p) in parts.iter().enumerate() {
                finite_knots(&format!("{what} mixture[{i}]"), &p.chao)?;
                if !(p.weight.is_finite() && p.weight > 0.0) {
                    return invalid(format!(
                        "{what}: mixture[{i}] weight must be > 0, got {}",
                        p.weight
                    ));
                }
                sum += p.weight;
            }
            if (sum - 1.0).abs() > MIXTURE_SUM_SLACK {
                return invalid(format!("{what}: mixture weights sum to {sum}, expected 1"));
            }
            Ok(Realization::Mixture(
                parts
                    .iter()
                    .map(|p| (p.chao.clone(), p.weight / sum))
                    .collect(),
            ))
        }
        (Some(_), Some(_)) => invalid(format!("{what}: give either `chao` or `mixture`, not both")),
        (None, None) => invalid(format!("{what}: needs `chao` or `mixture`")),
    }
}
