//! [`synth_fluent`]: syllables run together, as fluent speakers say them.

use std::f64::consts::{PI, TAU};

use tonekit_core::SAMPLE_RATE;

use crate::pitch::{chao_at, chao_to_st_f64, st_to_hz};
use crate::render::{finish, harmonic_sum, ramp_gain, NoiseFill, ONSET_NOISE, RAMP_MS};
use crate::Synth;

/// One syllable of a [`FluentSpec`].
#[derive(Clone, Debug, PartialEq)]
pub struct FluentSyllable {
    /// Chao knots (unclamped; 1 = floor, 5 = ceiling), evenly spaced over the voiced part. May be
    /// empty only if the syllable has no voiced part.
    pub chao: Vec<f32>,
    /// Syllable length, unvoiced onset included. The next syllable starts right after it.
    pub dur_ms: f32,
    /// Leading fricative noise (a consonant such as s, sh or x). It breaks the voicing, so the
    /// join into this syllable has no glide and no dip. Equal to `dur_ms` (or more) means fully
    /// whispered.
    pub unvoiced_onset_ms: f32,
}

impl FluentSyllable {
    /// A syllable spoken at `syllables_per_s` (its length is `1000 / syllables_per_s` ms), with no
    /// unvoiced onset.
    pub fn at_rate(chao: Vec<f32>, syllables_per_s: f32) -> Self {
        Self {
            chao,
            dur_ms: 1000.0 / syllables_per_s,
            unvoiced_onset_ms: 0.0,
        }
    }
}

/// Contiguous syllables with coarticulation. See the crate docs for the signal model.
#[derive(Clone, Debug, PartialEq)]
pub struct FluentSpec {
    /// Chao 1 in Hz. Must be positive.
    pub floor_hz: f32,
    /// Chao 5 in Hz. Must be positive.
    pub ceil_hz: f32,
    pub lead_ms: f32,
    pub tail_ms: f32,
    pub syllables: Vec<FluentSyllable>,
    /// Full width of the raised-cosine f0 transition centred on each voiced join (0 = a step).
    pub glide_ms: f32,
    /// Depth of the energy dip at each voiced join, in dB (0 = none).
    pub dip_db: f32,
    /// Full width of that dip (a raised cosine in dB, centred on the join).
    pub dip_ms: f32,
    pub snr_db: Option<f32>,
    pub seed: u64,
}

/// Where one syllable lives in the sample buffer.
struct Part {
    /// Unvoiced-onset noise, `[start, end)`.
    onset: (usize, usize),
    /// Voiced part, `[start, end)`.
    voiced: (usize, usize),
}

impl Part {
    fn voiced_len(&self) -> usize {
        self.voiced.1 - self.voiced.0
    }
}

/// Renders `spec`: contiguous syllables whose voicing runs on across every join that the next
/// syllable does not open with a consonant. See the crate docs for the signal model.
///
/// # Panics
///
/// If `floor_hz` or `ceil_hz` is not positive, or if a syllable with a voiced part has no `chao`
/// knots.
pub fn synth_fluent(spec: &FluentSpec) -> Synth {
    assert!(
        spec.floor_hz > 0.0 && spec.ceil_hz > 0.0,
        "floor_hz and ceil_hz must be positive"
    );
    let (floor_hz, ceil_hz) = (f64::from(spec.floor_hz), f64::from(spec.ceil_hz));
    let sr = f64::from(SAMPLE_RATE);
    let to_sample = |ms: f64| (ms.max(0.0) * sr / 1000.0).round() as usize;
    let to_frame = |ms: f64| (ms / 10.0).round() as u32;

    // --- Timeline: syllables back to back, rounded once per boundary. ---
    let mut t_ms = f64::from(spec.lead_ms).max(0.0);
    let mut parts = Vec::with_capacity(spec.syllables.len());
    let mut syllable_frames = Vec::with_capacity(spec.syllables.len());
    for syllable in &spec.syllables {
        let dur = f64::from(syllable.dur_ms).max(0.0);
        let onset = f64::from(syllable.unvoiced_onset_ms).clamp(0.0, dur);
        let (start, voiced_start, end) = (t_ms, t_ms + onset, t_ms + dur);
        syllable_frames.push((to_frame(start), to_frame(end)));
        parts.push(Part {
            onset: (to_sample(start), to_sample(voiced_start)),
            voiced: (to_sample(voiced_start), to_sample(end)),
        });
        t_ms = end;
    }
    let total = to_sample(t_ms + f64::from(spec.tail_ms).max(0.0));

    // --- Each syllable's own contour, in semitones, over its voiced part. ---
    let mut st: Vec<Option<f64>> = vec![None; total];
    for (syllable, part) in spec.syllables.iter().zip(&parts) {
        let n = part.voiced_len();
        if n == 0 {
            continue;
        }
        assert!(
            !syllable.chao.is_empty(),
            "a syllable with a voiced part needs at least one chao knot"
        );
        for k in 0..n {
            let u = if n > 1 {
                k as f64 / (n - 1) as f64
            } else {
                0.0
            };
            st[part.voiced.0 + k] = Some(chao_to_st_f64(
                chao_at(&syllable.chao, u),
                floor_hz,
                ceil_hz,
            ));
        }
    }

    // --- Voiced joins: the voicing runs straight from one syllable into the next. ---
    let joins: Vec<(usize, usize, usize)> = parts
        .windows(2)
        .filter(|w| w[1].onset.0 == w[1].onset.1 && w[0].voiced_len() > 0 && w[1].voiced_len() > 0)
        .map(|w| (w[1].voiced.0, w[0].voiced_len(), w[1].voiced_len()))
        .collect();

    // --- Glides: a raised cosine in semitones from the left syllable's contour to the right's. ---
    let half_glide = to_sample(f64::from(spec.glide_ms)) / 2;
    for &(join, n_left, n_right) in &joins {
        let half = half_glide.min(n_left / 2).min(n_right / 2);
        if half == 0 {
            continue;
        }
        let (a, b) = (join - half, join + half);
        let (left, right) = (st[a].unwrap_or(0.0), st[b].unwrap_or(0.0));
        for (t, value) in st.iter_mut().enumerate().take(b).skip(a) {
            let w = 0.5 * (1.0 - (PI * (t - a) as f64 / (b - a) as f64).cos());
            *value = Some(left + (right - left) * w);
        }
    }

    // --- Amplitude: ramps at the edges of each voiced stretch, dips at the voiced joins. ---
    let mut gain = vec![1.0_f64; total];
    let ramp_len = to_sample(RAMP_MS);
    let mut t = 0;
    while t < total {
        if st[t].is_none() {
            t += 1;
            continue;
        }
        let start = t;
        while t < total && st[t].is_some() {
            t += 1;
        }
        let n = t - start;
        let ramp = ramp_len.min(n / 2);
        for k in 0..n {
            gain[start + k] *= ramp_gain(k, ramp) * ramp_gain(n - 1 - k, ramp);
        }
    }
    let half_dip = to_sample(f64::from(spec.dip_ms)) / 2;
    if half_dip > 0 && spec.dip_db != 0.0 {
        for &(join, _, _) in &joins {
            for (t, g) in gain
                .iter_mut()
                .enumerate()
                .take((join + half_dip).min(total))
                .skip(join.saturating_sub(half_dip))
            {
                let c = 0.5 * (1.0 + (PI * (t as f64 - join as f64) / half_dip as f64).cos());
                *g *= 10.0_f64.powf(-f64::from(spec.dip_db) * c / 20.0);
            }
        }
    }

    // --- Harmonic layer: one phase per voiced stretch, so a join has no phase jump. ---
    let mut signal = vec![0.0_f64; total];
    let mut f0_at_sample: Vec<Option<f32>> = vec![None; total];
    let mut phase = 0.0_f64;
    for t in 0..total {
        let Some(semitones) = st[t] else {
            phase = 0.0;
            continue;
        };
        let hz = st_to_hz(semitones);
        f0_at_sample[t] = Some(hz as f32);
        signal[t] = harmonic_sum(phase, hz) * gain[t];
        phase = (phase + TAU * hz / sr) % TAU;
    }

    let fills: Vec<NoiseFill> = parts
        .iter()
        .map(|part| NoiseFill {
            start: part.onset.0,
            end: part.onset.1,
            rel_sigma: ONSET_NOISE,
        })
        .collect();
    finish(
        signal,
        &f0_at_sample,
        &fills,
        spec.snr_db,
        spec.seed,
        syllable_frames,
    )
}
