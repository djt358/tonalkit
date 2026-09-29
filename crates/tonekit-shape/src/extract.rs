//! ToneShape extraction from an f0 track and a syllable span (spec §5, §7).

use tonekit_core::{F0Track, MeasureIssue, Register, TbuSpan, ToneShape, CONTOUR_POINTS};

use crate::chao::{st_to_chao_f64, voiced_st};
use crate::fit::{line_slope, quadratic_coefficient, turning_point};

/// Milliseconds per frame (`HOP` samples at 16 kHz).
const FRAME_MS: f32 = 10.0;
/// Seconds per frame.
const FRAME_S: f64 = 0.01;
/// Fewer voiced frames than this and there is no shape to speak of.
const MIN_VOICED_FRAMES: usize = 3;
/// A voiced part shorter than this many milliseconds is `TooShort`.
const MIN_VOICED_MS: f32 = 80.0;
/// Each contour point averages ±this fraction of the voiced part's duration...
const WINDOW_FRACTION: f64 = 0.05;
/// ...but never less than one frame in total (±half a frame).
const MIN_HALF_WINDOW: f64 = 0.5;
/// Slack when deciding which frames fall inside a window.
const EDGE_EPS: f64 = 1e-9;

/// Mean of the piecewise-linear curve through `values` (one per frame, unit spacing) over
/// `[a, b]`, which lies within `[0, values.len() − 1]`; the curve's value at `a` if `b == a`.
fn window_mean(values: &[f64], a: f64, b: f64) -> f64 {
    let last = values.len() - 1;
    let at = |t: f64| {
        let i = (t.floor() as usize).min(last - 1);
        let f = t - i as f64;
        values[i] * (1.0 - f) + values[i + 1] * f
    };
    if b - a < EDGE_EPS {
        return at(a);
    }
    // Trapezoids between `a`, every whole frame position inside the window, and `b`.
    let (mut t0, mut v0) = (a, at(a));
    let mut next = a.floor() + 1.0;
    let mut area = 0.0;
    while t0 < b {
        let t1 = next.min(b);
        let v1 = at(t1);
        area += 0.5 * (v0 + v1) * (t1 - t0);
        (t0, v0) = (t1, v1);
        next += 1.0;
    }
    area / (b - a)
}

/// A shape and the measurement caveats found while extracting it.
#[derive(Clone, Debug, PartialEq)]
pub struct Extracted {
    pub shape: ToneShape,
    pub issues: Vec<MeasureIssue>,
}

/// Extracts the Chao-scale shape of the syllable in `span` from `f0`, normalised by `r`.
///
/// The voiced part runs from the first to the last voiced frame in the span (a voiced frame has
/// an f0, `hz.is_some()`: the provider's own voicing decision, ruling R32); unvoiced frames inside
/// it are filled by linear interpolation in semitones. `Err(Unvoiced)` if the span holds fewer than three voiced frames. A voiced part
/// under 80 ms still yields a shape, flagged [`MeasureIssue::TooShort`].
///
/// - `contour[k]` is centred at fraction `k/(K−1)` of the voiced part and is the mean of the
///   (interpolated) curve over ±5 % of its duration: at least one frame wide, and narrowing
///   symmetrically at the ends so the end points are not pulled inwards. The mean is taken over
///   the piecewise-linear curve rather than over whichever whole frames fall inside the window,
///   because the latter is off-centre for most `k` and biases sloped contours by up to half a
///   frame's worth of slope. `voiced_weights[k]` is the fraction of the frames inside the window
///   that were truly voiced. `onset`/`offset` are the first/last contour points, `mean` and
///   `range` are the mean and max − min of the contour.
/// - `slope` is the least-squares slope of Chao against time in seconds over the truly voiced
///   frames; `curvature` is the quadratic coefficient of a least-squares fit against the voiced
///   part's normalised time (0..1).
/// - `voiced_fraction` is the share of the span's frames that are voiced; `f0_confidence` is the
///   mean `voiced_p` of the voiced frames, the only place `voiced_p` enters.
/// - `turning_point` follows ruling R4 (see the private `fit` module).
pub fn extract(f0: &F0Track, span: &TbuSpan, r: &Register) -> Result<Extracted, MeasureIssue> {
    let start = span.start_frame as usize;
    let end = (span.end_frame as usize).min(f0.frames.len());
    if start >= end {
        return Err(MeasureIssue::Unvoiced);
    }

    // Truly voiced frames: (frame index, semitones, voiced_p).
    let voiced: Vec<(usize, f64, f32)> = (start..end)
        .filter_map(|i| {
            let frame = &f0.frames[i];
            voiced_st(frame).map(|st| (i, st, frame.voiced_p))
        })
        .collect();
    if voiced.len() < MIN_VOICED_FRAMES {
        return Err(MeasureIssue::Unvoiced);
    }

    // The voiced part as a per-frame semitone series, holes interpolated.
    let first = voiced[0].0;
    let n = voiced[voiced.len() - 1].0 - first + 1;
    let mut st = vec![0.0_f64; n];
    let mut is_voiced = vec![false; n];
    for &(i, s, _) in &voiced {
        st[i - first] = s;
        is_voiced[i - first] = true;
    }
    let mut prev = 0;
    for j in 1..n {
        if !is_voiced[j] {
            continue;
        }
        for g in prev + 1..j {
            let t = (g - prev) as f64 / (j - prev) as f64;
            st[g] = st[prev] + t * (st[j] - st[prev]);
        }
        prev = j;
    }
    let chao: Vec<f64> = st.iter().map(|&s| st_to_chao_f64(s, r)).collect();

    // Contour and its voiced weights.
    let last_index = (n - 1) as f64;
    let half_window = (WINDOW_FRACTION * n as f64).max(MIN_HALF_WINDOW);
    let mut contour = Vec::with_capacity(CONTOUR_POINTS);
    let mut voiced_weights = Vec::with_capacity(CONTOUR_POINTS);
    for k in 0..CONTOUR_POINTS {
        let x = k as f64 / (CONTOUR_POINTS - 1) as f64 * last_index;
        // Symmetric about x, and narrowing at the ends so the end points are not pulled inwards.
        let w = half_window.min(x).min(last_index - x);
        contour.push(window_mean(&chao, x - w, x + w) as f32);
        // Frames inside the window; a window of width ≥ 1 frame always has one.
        let lo = (x - w - EDGE_EPS).ceil().max(0.0) as usize;
        let hi = ((x + w + EDGE_EPS).floor().min(last_index)) as usize;
        let (lo, hi) = if lo <= hi {
            (lo, hi)
        } else {
            let nearest = (x.round() as usize).min(n - 1);
            (nearest, nearest)
        };
        let truly_voiced = is_voiced[lo..=hi].iter().filter(|&&v| v).count();
        voiced_weights.push((truly_voiced as f64 / (hi - lo + 1) as f64) as f32);
    }

    // Slope over time in seconds, curvature over normalised time, both on truly voiced frames.
    let by_seconds: Vec<(f64, f64)> = voiced
        .iter()
        .map(|&(i, _, _)| ((i - first) as f64 * FRAME_S, chao[i - first]))
        .collect();
    let by_fraction: Vec<(f64, f64)> = voiced
        .iter()
        .map(|&(i, _, _)| ((i - first) as f64 / last_index, chao[i - first]))
        .collect();
    let slope = line_slope(&by_seconds) as f32;
    let curvature = quadratic_coefficient(&by_fraction) as f32;

    // Turning point on the 3-frame-smoothed voiced curve.
    let smoothed: Vec<f64> = (0..n)
        .map(|j| {
            let window = &chao[j.saturating_sub(1)..=(j + 1).min(n - 1)];
            window.iter().sum::<f64>() / window.len() as f64
        })
        .collect();

    let (lo, hi) = contour
        .iter()
        .fold((f32::INFINITY, f32::NEG_INFINITY), |(lo, hi), &c| {
            (lo.min(c), hi.max(c))
        });
    let span_frames = span.end_frame.saturating_sub(span.start_frame) as f32;
    let shape = ToneShape {
        span: span.clone(),
        onset: contour[0],
        offset: contour[CONTOUR_POINTS - 1],
        mean: contour.iter().sum::<f32>() / CONTOUR_POINTS as f32,
        slope,
        curvature,
        turning_point: turning_point(&smoothed),
        range: hi - lo,
        duration_ms: span_frames * FRAME_MS,
        voiced_fraction: voiced.len() as f32 / span_frames,
        f0_confidence: voiced.iter().map(|v| v.2).sum::<f32>() / voiced.len() as f32,
        phonation: None,
        contour,
        voiced_weights,
    };

    let mut issues = Vec::new();
    if (n as f32) * FRAME_MS < MIN_VOICED_MS {
        issues.push(MeasureIssue::TooShort);
    }
    Ok(Extracted { shape, issues })
}
