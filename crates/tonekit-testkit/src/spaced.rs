//! [`synth`]: syllables with silence between them (the P0 generator).

use std::f64::consts::TAU;

use tonekit_core::SAMPLE_RATE;

use crate::pitch::{chao_at, chao_to_hz_f64};
use crate::render::{
    finish, harmonic_sum, ramp_gain, NoiseFill, CREAK_NOISE, ONSET_NOISE, RAMP_MS,
};
use crate::Synth;

/// One syllable of a [`SynthSpec`].
#[derive(Clone, Debug, PartialEq)]
pub struct SynthSyllable {
    /// Chao knots (unclamped; 1 = floor, 5 = ceiling), evenly spaced over the voiced part. One knot
    /// is a level tone. May be empty only if the syllable has no voiced part.
    pub chao: Vec<f32>,
    /// Syllable length, unvoiced onset included, gap excluded.
    pub dur_ms: f32,
    pub gap_after_ms: f32,
    /// Leading noise. Equal to `dur_ms` (or more) means fully whispered.
    pub unvoiced_onset_ms: f32,
    /// Fraction range `[a, b)` of the voiced part with no f0 and low-level noise.
    pub creak: Option<(f32, f32)>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SynthSpec {
    /// Chao 1 in Hz. Must be positive.
    pub floor_hz: f32,
    /// Chao 5 in Hz. Must be positive.
    pub ceil_hz: f32,
    pub lead_ms: f32,
    pub tail_ms: f32,
    pub syllables: Vec<SynthSyllable>,
    pub snr_db: Option<f32>,
    pub seed: u64,
}

/// Where one syllable lives in the sample buffer.
struct Placement {
    /// Unvoiced-onset noise, `[start, end)`.
    onset: (usize, usize),
    /// Voiced part including any creak, `[start, end)`.
    voiced: (usize, usize),
    /// Creak samples inside `voiced`, `[start, end)`.
    creak: (usize, usize),
}

/// Renders `spec`. See the crate docs for the signal model and ground-truth conventions.
///
/// # Panics
///
/// If `floor_hz` or `ceil_hz` is not positive, or if a syllable with a voiced part has no `chao`
/// knots.
pub fn synth(spec: &SynthSpec) -> Synth {
    assert!(
        spec.floor_hz > 0.0 && spec.ceil_hz > 0.0,
        "floor_hz and ceil_hz must be positive"
    );
    let (floor_hz, ceil_hz) = (f64::from(spec.floor_hz), f64::from(spec.ceil_hz));
    let sr = f64::from(SAMPLE_RATE);
    let to_sample = |ms: f64| (ms * sr / 1000.0).round() as usize;
    let to_frame = |ms: f64| (ms / 10.0).round() as u32;

    // --- Timeline: everything is placed in ms first, then rounded once per boundary. ---
    let mut t_ms = f64::from(spec.lead_ms).max(0.0);
    let mut placements = Vec::with_capacity(spec.syllables.len());
    let mut syllable_frames = Vec::with_capacity(spec.syllables.len());
    for syllable in &spec.syllables {
        let dur = f64::from(syllable.dur_ms).max(0.0);
        let onset = f64::from(syllable.unvoiced_onset_ms).clamp(0.0, dur);
        let (start, voiced_start, end) = (t_ms, t_ms + onset, t_ms + dur);
        syllable_frames.push((to_frame(start), to_frame(end)));

        let voiced = (to_sample(voiced_start), to_sample(end));
        let n_voiced = (voiced.1 - voiced.0) as f64;
        let creak = match syllable.creak {
            Some((a, b)) => {
                let edge =
                    |f: f32| voiced.0 + (f64::from(f).clamp(0.0, 1.0) * n_voiced).round() as usize;
                (edge(a), edge(b).max(edge(a)))
            }
            None => (voiced.0, voiced.0),
        };
        placements.push(Placement {
            onset: (to_sample(start), voiced.0),
            voiced,
            creak,
        });
        t_ms = end + f64::from(syllable.gap_after_ms).max(0.0);
    }
    let total = to_sample(t_ms + f64::from(spec.tail_ms).max(0.0));

    // --- Harmonic layer, and the f0 it was built from. ---
    let mut signal = vec![0.0_f64; total];
    let mut f0_at_sample: Vec<Option<f32>> = vec![None; total];
    let ramp_len = to_sample(RAMP_MS);
    for (syllable, place) in spec.syllables.iter().zip(&placements) {
        let (vs, ve) = place.voiced;
        let n = ve - vs;
        if n == 0 {
            continue;
        }
        assert!(
            !syllable.chao.is_empty(),
            "a syllable with a voiced part needs at least one chao knot"
        );
        let ramp = ramp_len.min(n / 2);
        let mut phase = 0.0_f64;
        for k in 0..n {
            let sample = vs + k;
            let u = if n > 1 {
                k as f64 / (n - 1) as f64
            } else {
                0.0
            };
            let hz = chao_to_hz_f64(chao_at(&syllable.chao, u), floor_hz, ceil_hz);
            let in_creak = (place.creak.0..place.creak.1).contains(&sample);
            if !in_creak {
                f0_at_sample[sample] = Some(hz as f32);
                signal[sample] =
                    harmonic_sum(phase, hz) * ramp_gain(k, ramp) * ramp_gain(n - 1 - k, ramp);
            }
            phase = (phase + TAU * hz / sr) % TAU;
        }
    }

    // --- Noise (onset and creak, in timeline order), SNR, level and truth. ---
    let fills: Vec<NoiseFill> = placements
        .iter()
        .flat_map(|place| {
            [
                NoiseFill {
                    start: place.onset.0,
                    end: place.onset.1,
                    rel_sigma: ONSET_NOISE,
                },
                NoiseFill {
                    start: place.creak.0,
                    end: place.creak.1,
                    rel_sigma: CREAK_NOISE,
                },
            ]
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
