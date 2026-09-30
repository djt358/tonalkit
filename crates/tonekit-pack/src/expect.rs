//! Expectation resolution (spec §6.2 resolution order, §6.3 grading against accent and imprint).
//!
//! `expect_tone` resolves one tone in one context: the most specific matching `realize` rule in
//! the graded accent, else up the `inherits` chain, else the tone's citation. `expect` combines
//! those over a target's lexical variants. Both blend an imprint `StyleProfile` when present.

use tonekit_core::{GradingTarget, ToneId, ToneTarget, CONTOUR_POINTS};

use crate::error::{invalid, PackError};
use crate::{Citation, LanguagePack, Realization, Rule};

/// Style observations required before an imprint may move a tone's expectation (spec §6.3).
const MIN_STYLE_OBSERVATIONS: u32 = 5;
/// Rounding slack when variant weights add up to exactly 1 in f32.
const VARIANT_SUM_SLACK: f32 = 1e-6;

/// Gaussian scales (σ) in Chao units, before any widening for measurement issues.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Tolerance {
    pub contour: f32,
    pub onset: f32,
    pub offset: f32,
    pub turning_point: f32,
}

/// One weighted realisation of a tone.
#[derive(Clone, Debug, PartialEq)]
pub struct Component {
    /// `"{accent}/{rule_label}"`, `"{accent}/{rule_label}#{i}"` for mixture component `i`
    /// (from 0), or `"{accent}/citation"`. The accent is the one that owns the matched rule
    /// (so an inherited rule reads `"cmn-standard/t5-after-1"` when grading `cmn-TW`); for the
    /// citation it is the graded accent.
    pub label: String,
    /// The tone this component realises: the target's main tone or one of its lexical variants.
    pub tone: ToneId,
    pub weight: f32,
    /// Chao units, `CONTOUR_POINTS` long.
    pub contour: Vec<f32>,
    /// First and last point of `contour`.
    pub onset: f32,
    pub offset: f32,
    pub sigma: Tolerance,
}

/// A Gaussian mixture in feature space; `components` weights sum to 1.
#[derive(Clone, Debug, PartialEq)]
pub struct Expectation {
    pub components: Vec<Component>,
}

/// Where a syllable sits in its phrase, as the caller knows it.
#[derive(Clone, Debug, PartialEq)]
pub struct TargetContext {
    pub index: u32,
    pub count: u32,
    /// The previous syllable's tone, if any.
    pub prev: Option<ToneId>,
    pub phrase_final: bool,
}

impl LanguagePack {
    /// Expected shape of `tone` in `ctx` under the graded accent, with style blending.
    ///
    /// Errors: `UnknownAccent`, `UnknownTone` (also for `ctx.prev`), `Invalid` for a malformed
    /// style profile.
    pub fn expect_tone(
        &self,
        grading: &GradingTarget,
        tone: &ToneId,
        ctx: &TargetContext,
    ) -> Result<Expectation, PackError> {
        let accent = self
            .accent_index(&grading.accent)
            .ok_or_else(|| PackError::UnknownAccent(grading.accent.clone()))?;
        let tone_idx = self
            .tone_index(tone)
            .ok_or_else(|| PackError::UnknownTone(tone.clone()))?;
        if let Some(prev) = &ctx.prev {
            if self.tone_index(prev).is_none() {
                return Err(PackError::UnknownTone(prev.clone()));
            }
        }
        let mut components = self.resolve(accent, tone_idx, ctx)?;
        blend_style(grading, &mut components)?;
        Ok(Expectation { components })
    }

    /// Expected shape of a target: the main tone takes `1 − Σ variant weights`, each lexical
    /// variant its own weight, and each tone's realisation components share that weight.
    ///
    /// Errors as `expect_tone`, plus `Invalid` when a variant weight is negative or non-finite or
    /// the variants outweigh 1.
    pub fn expect(
        &self,
        grading: &GradingTarget,
        target: &ToneTarget,
        ctx: &TargetContext,
    ) -> Result<Expectation, PackError> {
        let mut variant_sum = 0.0f32;
        for v in &target.lexical_variants {
            if !(v.weight.is_finite() && v.weight >= 0.0) {
                return invalid(format!(
                    "lexical variant {:?} has weight {}; weights must be >= 0",
                    v.tone.0, v.weight
                ));
            }
            variant_sum += v.weight;
        }
        let main_weight = 1.0 - variant_sum;
        if main_weight < -VARIANT_SUM_SLACK {
            return invalid(format!(
                "lexical variant weights sum to {variant_sum}; they must leave the main tone a weight >= 0"
            ));
        }

        let mut components = Vec::new();
        let weighted = std::iter::once((&target.tone, main_weight.max(0.0)))
            .chain(target.lexical_variants.iter().map(|v| (&v.tone, v.weight)));
        for (tone, weight) in weighted {
            // Resolve even a zero-weight tone so an unknown tone is always reported.
            let expectation = self.expect_tone(grading, tone, ctx)?;
            components.extend(expectation.components.into_iter().filter_map(|mut c| {
                c.weight *= weight;
                (c.weight > 0.0).then_some(c)
            }));
        }
        Ok(Expectation { components })
    }

    /// Resolve `tone_idx` in `ctx` under `accent` without style: rule search, then citation.
    pub(crate) fn resolve(
        &self,
        accent: usize,
        tone_idx: usize,
        ctx: &TargetContext,
    ) -> Result<Vec<Component>, PackError> {
        let tone = &self.inventory[tone_idx];
        let graded = &self.accents[accent];
        let sigma = graded.tolerance;
        let make = |label: String, weight: f32, knots: &[f32]| {
            let contour = expand_knots(knots, CONTOUR_POINTS);
            Component {
                label,
                tone: tone.clone(),
                weight,
                onset: contour[0],
                offset: contour[CONTOUR_POINTS - 1],
                contour,
                sigma,
            }
        };

        if let Some((owner, rule)) = self.find_rule(accent, tone, ctx) {
            let owner = &self.accents[owner].id.0;
            return Ok(match &rule.realization {
                Realization::Single(knots) => {
                    vec![make(format!("{owner}/{}", rule.label), 1.0, knots)]
                }
                Realization::Mixture(parts) => parts
                    .iter()
                    .enumerate()
                    .map(|(i, (knots, weight))| {
                        make(format!("{owner}/{}#{i}", rule.label), *weight, knots)
                    })
                    .collect(),
            });
        }
        match &self.citations[tone_idx] {
            Citation::Knots(knots) => {
                Ok(vec![make(format!("{}/citation", graded.id.0), 1.0, knots)])
            }
            Citation::Context => Err(PackError::MissingRealization {
                tone: tone.clone(),
                context: format!(
                    "accent {:?}, prev {}, phrase_final {}",
                    graded.id.0,
                    ctx.prev
                        .as_ref()
                        .map_or("none".to_string(), |p| format!("{:?}", p.0)),
                    ctx.phrase_final
                ),
            }),
        }
    }

    /// The most specific matching rule in `accent`; if none matches, the same in its parent, and
    /// so on. Specificity is the number of `when` keys; ties go to the first rule in file order.
    /// Returns the index of the accent that owns the rule.
    fn find_rule(
        &self,
        accent: usize,
        tone: &ToneId,
        ctx: &TargetContext,
    ) -> Option<(usize, &Rule)> {
        let mut current = Some(accent);
        while let Some(i) = current {
            let a = &self.accents[i];
            let mut best: Option<&Rule> = None;
            for rule in a.rules.iter().filter(|r| matches(r, tone, ctx)) {
                // Strictly greater: an equally specific later rule never displaces the first.
                if best.is_none_or(|b| specificity(rule) > specificity(b)) {
                    best = Some(rule);
                }
            }
            if let Some(rule) = best {
                return Some((i, rule));
            }
            current = a.inherits;
        }
        None
    }
}

fn specificity(rule: &Rule) -> usize {
    let w = &rule.when;
    usize::from(w.tone.is_some())
        + usize::from(w.prev.is_some())
        + usize::from(w.phrase_final.is_some())
}

fn matches(rule: &Rule, tone: &ToneId, ctx: &TargetContext) -> bool {
    let w = &rule.when;
    w.tone.as_ref().is_none_or(|t| t == tone)
        && w.prev.as_ref().is_none_or(|p| ctx.prev.as_ref() == Some(p))
        && w.phrase_final.is_none_or(|f| f == ctx.phrase_final)
}

/// Linear interpolation of `knots` (at `u = k/(len−1)`) onto `n` points at `u = i/(n−1)`.
/// `knots` must be non-empty and `n >= 2`.
fn expand_knots(knots: &[f32], n: usize) -> Vec<f32> {
    let last = knots.len() - 1;
    if last == 0 {
        return vec![knots[0]; n];
    }
    if knots.len() == n {
        return knots.to_vec();
    }
    (0..n)
        .map(|i| {
            if i == n - 1 {
                return knots[last];
            }
            let pos = i as f64 / (n - 1) as f64 * last as f64;
            let j = (pos.floor() as usize).min(last - 1);
            let frac = pos - j as f64;
            (f64::from(knots[j]) + frac * f64::from(knots[j + 1] - knots[j])) as f32
        })
        .collect()
}

/// `(1 − α)·component + α·style` for every component whose tone has a style entry with enough
/// observations; α is `style_weight` clamped to [0, 1]. Onset and offset follow the blended
/// contour's endpoints.
fn blend_style(grading: &GradingTarget, components: &mut [Component]) -> Result<(), PackError> {
    let Some(style) = &grading.style else {
        return Ok(());
    };
    if !grading.style_weight.is_finite() {
        return invalid(format!(
            "style_weight must be finite, got {}",
            grading.style_weight
        ));
    }
    let alpha = grading.style_weight.clamp(0.0, 1.0);
    if alpha == 0.0 {
        return Ok(());
    }
    for c in components {
        let Some(st) = style.tones.iter().find(|s| s.tone == c.tone) else {
            continue;
        };
        if st.n < MIN_STYLE_OBSERVATIONS {
            continue;
        }
        if st.contour.is_empty() || st.contour.iter().any(|v| !v.is_finite()) {
            return invalid(format!(
                "style contour for tone {:?} is empty or not finite",
                st.tone.0
            ));
        }
        let style_contour = expand_knots(&st.contour, CONTOUR_POINTS);
        for (a, s) in c.contour.iter_mut().zip(&style_contour) {
            *a = (1.0 - alpha) * *a + alpha * s;
        }
        c.onset = c.contour[0];
        c.offset = c.contour[CONTOUR_POINTS - 1];
    }
    Ok(())
}
