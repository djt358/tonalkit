//! Calibrated likelihoods, the LLR of a target against a background of all tones, and the
//! per-syllable judgement (spec §7.1).
//!
//! For a shape `x` and an expectation component `c` with tolerance σ (every σ widened by
//! [`widen_for`] when the measurement is poor):
//!
//! ```text
//! d²(x,c)    = WRMS(x.contour − c.contour; w)²/σc² + ½(Δonset/σon)² + ½(Δoffset/σoff)²
//! log p(x|c) = −½·d² − ln(σc·σon·σoff)
//! ```
//!
//! A tone's likelihood is the mixture over its components, divided by the pack's calibration
//! temperature. The LLR compares a target's mixture with the prior-weighted mixture of every tone
//! in the inventory, so syllables of any length contribute evidence *relative to a background*.
//!
//! Every f32 that leaves this module is finite (ruling R12): log-values are clamped to
//! `±LOG_CLAMP`, and a shape with non-finite numbers is uninformative rather than an error.

use tonekit_core::{
    GradingTarget, MeasureIssue, Measured, ToneId, ToneJudgement, ToneShape, ToneTarget,
    CONTOUR_POINTS,
};

use crate::deltas;
use crate::error::{invalid, PackError};
use crate::{Component, Expectation, LanguagePack, TargetContext};

/// Log-values are clamped into `[-LOG_CLAMP, LOG_CLAMP]`; `-LOG_CLAMP` is also what a shape
/// with no usable numbers scores.
const LOG_CLAMP: f64 = 1.0e6;
/// Tolerance multiplier under `LowSnr`, `Clipped` or `ColdStartRegister`.
const WIDEN: f32 = 1.5;
/// Every point counts for at least this much, however unvoiced.
const MIN_POINT_WEIGHT: f32 = 0.25;
/// Inside an `unvoiced_ok` region, points voiced less than this carry no weight.
const UNVOICED_BELOW: f32 = 0.5;

/// The factor applied to every tolerance σ: 1.5 if the measurement had `LowSnr`, `Clipped` or
/// `ColdStartRegister`, else 1.0.
pub fn widen_for(issues: &[MeasureIssue]) -> f32 {
    let poor = issues.iter().any(|i| {
        matches!(
            i,
            MeasureIssue::LowSnr | MeasureIssue::Clipped | MeasureIssue::ColdStartRegister
        )
    });
    if poor {
        WIDEN
    } else {
        1.0
    }
}

/// How a call's issues and the pack's calibration change scoring.
#[derive(Clone, Copy)]
struct Scoring {
    widen: f64,
    /// False under `TooShort`: the interior of the contour is not evidence.
    contour_term: bool,
    temperature: f64,
}

impl Scoring {
    fn new(pack: &LanguagePack, issues: &[MeasureIssue]) -> Scoring {
        Scoring {
            widen: f64::from(widen_for(issues)),
            contour_term: !issues.contains(&MeasureIssue::TooShort),
            temperature: f64::from(pack.calibration.temperature),
        }
    }

    /// Divide by the temperature and clamp.
    fn calibrate(&self, ll: f64) -> f32 {
        clamp_log(ll / self.temperature)
    }
}

/// `v` as an f32 in `[-LOG_CLAMP, LOG_CLAMP]`; NaN reads as the lower bound.
fn clamp_log(v: f64) -> f32 {
    if v.is_nan() {
        -LOG_CLAMP as f32
    } else {
        v.clamp(-LOG_CLAMP, LOG_CLAMP) as f32
    }
}

/// A running log-sum-exp; `EMPTY` is `−∞`.
#[derive(Clone, Copy)]
struct LogSumExp {
    max: f64,
    sum: f64,
}

impl LogSumExp {
    const EMPTY: LogSumExp = LogSumExp {
        max: f64::NEG_INFINITY,
        sum: 0.0,
    };

    fn add(&mut self, v: f64) {
        if v == f64::NEG_INFINITY {
            return;
        }
        if v > self.max {
            self.sum = self.sum * (self.max - v).exp() + 1.0;
            self.max = v;
        } else {
            self.sum += (v - self.max).exp();
        }
    }

    fn value(self) -> f64 {
        if self.sum > 0.0 {
            self.max + self.sum.ln()
        } else {
            f64::NEG_INFINITY
        }
    }
}

/// The best-scoring component of a mixture and its uncalibrated d².
struct Best {
    index: usize,
    d2: f64,
}

struct Mixture {
    /// Uncalibrated `logsumexp_c(ln w_c + log p(x|c))`; `−∞` with no components.
    ll: f64,
    best: Option<Best>,
}

/// Check the shape's structure. `Ok(true)` if every number is finite; `Ok(false)` if the shape
/// is unusable (non-finite contour, weights, onset or offset), which scores as no evidence.
fn check_shape(x: &ToneShape) -> Result<bool, PackError> {
    if x.contour.len() != CONTOUR_POINTS || x.voiced_weights.len() != CONTOUR_POINTS {
        return invalid(format!(
            "shape has {} contour points and {} voiced weights; both must be {CONTOUR_POINTS}",
            x.contour.len(),
            x.voiced_weights.len()
        ));
    }
    Ok(x.onset.is_finite()
        && x.offset.is_finite()
        && x.contour.iter().all(|v| v.is_finite())
        && x.voiced_weights.iter().all(|v| v.is_finite()))
}

impl LanguagePack {
    /// Calibrated log-likelihood of `x` under `tone` in `ctx` (mixture over the tone's
    /// realisations, divided by the pack temperature). The expectation is the only allocation.
    ///
    /// Errors: those of [`LanguagePack::expect_tone`], and `Invalid` if the shape's contour or
    /// `voiced_weights` are not `CONTOUR_POINTS` long. A shape with non-finite numbers scores
    /// `-1.0e6`.
    pub fn tone_loglik(
        &self,
        grading: &GradingTarget,
        x: &ToneShape,
        tone: &ToneId,
        ctx: &TargetContext,
        issues: &[MeasureIssue],
    ) -> Result<f32, PackError> {
        let usable = check_shape(x)?;
        let expectation = self.expect_tone(grading, tone, ctx)?;
        if !usable {
            return Ok(-LOG_CLAMP as f32);
        }
        let s = Scoring::new(self, issues);
        Ok(s.calibrate(self.mixture(x, &expectation, s).ll))
    }

    /// Judge one syllable against its intended target.
    ///
    /// - `loglik`: the calibrated log-likelihood under every inventory tone, in inventory order.
    /// - `llr_target`: the target's mixture (lexical variants included) against the
    ///   prior-weighted background of all tones, both calibrated.
    /// - `heard`: the tone with the largest posterior (prior × calibrated likelihood), if that
    ///   posterior reaches the pack's `heard_threshold`.
    /// - `distance` and `component`: the best-matching target component; the distance is √d²
    ///   and uncalibrated.
    /// - `deltas`: differences to that component: none under `LowSnr`, and only onset/offset
    ///   ones under `TooShort` (ruling R26).
    /// - `measured`: `Full` with no issues, else `Partial` carrying them.
    ///
    /// A shape with non-finite numbers is uninformative: `llr_target` 0, every `loglik` at
    /// `-1.0e6`, and no `heard`, `distance`, `component` or deltas.
    ///
    /// Errors as [`LanguagePack::expect`], plus `Invalid` for a shape whose contour or
    /// `voiced_weights` are not `CONTOUR_POINTS` long.
    pub fn judge(
        &self,
        grading: &GradingTarget,
        x: &ToneShape,
        target: &ToneTarget,
        ctx: &TargetContext,
        issues: &[MeasureIssue],
    ) -> Result<ToneJudgement, PackError> {
        let usable = check_shape(x)?;
        let s = Scoring::new(self, issues);

        // One expectation per inventory tone. A target without lexical variants *is* its main
        // tone's expectation, so that one is kept rather than resolved a second time.
        let mut loglik = Vec::with_capacity(self.inventory.len());
        let mut target_expectation = None;
        for tone in &self.inventory {
            let expectation = self.expect_tone(grading, tone, ctx)?;
            loglik.push(if usable {
                s.calibrate(self.mixture(x, &expectation, s).ll)
            } else {
                -LOG_CLAMP as f32
            });
            if target.lexical_variants.is_empty() && *tone == target.tone {
                target_expectation = Some(expectation);
            }
        }
        let target_expectation = match target_expectation {
            Some(e) => e,
            None => self.expect(grading, target, ctx)?,
        };

        let mut judgement = ToneJudgement {
            expected: target.tone.clone(),
            loglik,
            llr_target: 0.0,
            distance: None,
            component: None,
            heard: None,
            deltas: Vec::new(),
            measured: if issues.is_empty() {
                Measured::Full
            } else {
                Measured::Partial {
                    issues: issues.to_vec(),
                }
            },
        };
        if !usable {
            return Ok(judgement);
        }

        // Background and posterior: score_t = ln prior_t + calibrated loglik_t.
        let mut background = LogSumExp::EMPTY;
        let mut top: Option<(f64, usize)> = None;
        for (i, (prior, ll)) in self.prior.iter().zip(&judgement.loglik).enumerate() {
            let score = f64::from(*prior).ln() + f64::from(*ll);
            background.add(score);
            if top.is_none_or(|(best, _)| score > best) {
                top = Some((score, i));
            }
        }
        let background = background.value();

        let mixture = self.mixture(x, &target_expectation, s);
        judgement.llr_target = clamp_log(f64::from(s.calibrate(mixture.ll)) - background);

        if let Some((score, i)) = top {
            let posterior = (score - background).exp();
            if posterior >= f64::from(self.heard_threshold) {
                judgement.heard = Some(self.inventory[i].clone());
            }
        }

        if let Some(Best { index, d2 }) = mixture.best {
            let best = &target_expectation.components[index];
            judgement.distance = Some(d2.sqrt().min(f64::from(f32::MAX)) as f32);
            judgement.component = Some(best.label.clone());
            if !issues.contains(&MeasureIssue::LowSnr) {
                judgement.deltas = deltas::compute(x, best, s.widen, !s.contour_term);
            }
        }
        Ok(judgement)
    }

    /// The mixture of `expectation`'s components at `x`, with the best component tracked.
    fn mixture(&self, x: &ToneShape, expectation: &Expectation, s: Scoring) -> Mixture {
        let mut total = LogSumExp::EMPTY;
        let mut best: Option<(f64, Best)> = None;
        for (index, c) in expectation.components.iter().enumerate() {
            if c.weight <= 0.0 {
                continue;
            }
            let (ll, d2) = self.component(x, c, s);
            let score = f64::from(c.weight).ln() + ll;
            total.add(score);
            if best.as_ref().is_none_or(|(b, _)| score > *b) {
                best = Some((score, Best { index, d2 }));
            }
        }
        Mixture {
            ll: total.value(),
            best: best.map(|(_, b)| b),
        }
    }

    /// `(log p(x|c), d²)`, uncalibrated. `x` has finite numbers and `CONTOUR_POINTS` points.
    fn component(&self, x: &ToneShape, c: &Component, s: Scoring) -> (f64, f64) {
        let sigma_contour = f64::from(c.sigma.contour) * s.widen;
        let sigma_onset = f64::from(c.sigma.onset) * s.widen;
        let sigma_offset = f64::from(c.sigma.offset) * s.widen;

        let d_onset = f64::from(x.onset) - f64::from(c.onset);
        let d_offset = f64::from(x.offset) - f64::from(c.offset);
        let mut d2 = 0.5 * d_onset * d_onset / (sigma_onset * sigma_onset)
            + 0.5 * d_offset * d_offset / (sigma_offset * sigma_offset);
        if s.contour_term {
            if let Some(wrms2) = self.weighted_mean_square(x, c) {
                d2 += wrms2 / (sigma_contour * sigma_contour);
            }
        }
        (
            -0.5 * d2 - (sigma_contour * sigma_onset * sigma_offset).ln(),
            d2,
        )
    }

    /// `WRMS²` of `x.contour − c.contour`: `Σ w_k r_k² / Σ w_k` with `w_k = max(v_k, 0.25)`,
    /// except inside the `unvoiced_ok` region of the component's tone, where a point voiced
    /// less than 0.5 has `w_k = 0` (T3 creak is not evidence against T3). `None` if no point
    /// carries weight.
    fn weighted_mean_square(&self, x: &ToneShape, c: &Component) -> Option<f64> {
        let region = self.unvoiced_ok(&c.tone);
        let last = (CONTOUR_POINTS - 1) as f32;
        let (mut weighted, mut total) = (0.0f64, 0.0f64);
        for (k, ((xv, cv), voiced)) in x
            .contour
            .iter()
            .zip(&c.contour)
            .zip(&x.voiced_weights)
            .enumerate()
        {
            let u = k as f32 / last;
            let excused = *voiced < UNVOICED_BELOW && region.is_some_and(|(a, b)| a <= u && u <= b);
            let w = if excused {
                0.0
            } else {
                f64::from(voiced.max(MIN_POINT_WEIGHT))
            };
            let r = f64::from(*xv) - f64::from(*cv);
            weighted += w * r * r;
            total += w;
        }
        (total > 0.0).then(|| weighted / total)
    }
}
