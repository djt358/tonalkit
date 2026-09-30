//! Deterministic synthetic "speech" with exact f0 ground truth. Dev-only: no later crate ships it.
//!
//! [`synth`] renders a [`SynthSpec`] (a row of syllables, each a Chao contour plus timing) to 16 kHz
//! PCM together with the frame-level f0 the signal was built from, so f0 tracking, segmentation,
//! shape extraction and decoding can all be tested without audio files.
//!
//! # Signal model
//!
//! Timeline: `lead_ms` of silence; then per syllable `unvoiced_onset_ms` of noise, the voiced part
//! (`dur_ms - unvoiced_onset_ms`) and `gap_after_ms` of silence; then `tail_ms` of silence. Each
//! boundary is rounded to the nearest sample. An onset equal to (or longer than) `dur_ms` makes the
//! syllable fully whispered: noise only, no f0.
//!
//! - **Voiced part:** the sum over harmonics `h` with `h·f0 < 4000 Hz` of `sin(h·φ)/h`, where φ
//!   is accumulated per sample from the instantaneous f0. f0 comes from the syllable's Chao knots,
//!   evenly spaced over the voiced part (`u = i/(n−1)`), linearly interpolated in Chao and mapped
//!   to Hz per sample by [`chao_to_hz`]. A raised-cosine envelope ramps the amplitude over 20 ms at
//!   each edge (shrunk to half the part when it is shorter than 40 ms).
//! - **Creak:** `creak: Some((a, b))` replaces the fraction range `[a, b)` of the voiced part with
//!   noise and no f0. The pitch of the rest of the syllable does not move.
//! - **Noise levels:** Gaussian, with standard deviation 0.1 (unvoiced onset) or 0.05 (creak) times
//!   the voiced peak, meaning the largest |x| of the harmonic signal before normalisation (1.0 if
//!   there is none).
//! - **SNR:** `snr_db: Some(s)` adds white Gaussian noise over the whole buffer with RMS equal to
//!   the RMS of the voiced samples divided by `10^(s/20)`. Nothing is added when no sample is voiced.
//! - **Level:** finally the whole buffer is scaled so its peak |x| is 0.5.
//!
//! # Ground truth
//!
//! `f0_truth[i]` describes sample `i·160` (clamped to the last sample) and is `Some(hz)` exactly
//! when that sample is in a harmonic region; there are `pcm.len()/160 + 1` entries.
//! `syllable_frames[k]` is `(round(start_ms/10), round(end_ms/10))` for syllable `k`, spanning its
//! onset and voiced part but not its gap (half-open, halves round away from zero).
//!
//! # Determinism
//!
//! One seeded xorshift64 stream is drawn in timeline order (onset noise, creak
//! noise, then SNR noise), so a spec that needs no noise is independent of `seed`, and adding
//! `snr_db` does not change the onset or creak noise. The output is bit-identical for the same
//! spec on the same platform (it uses the platform's `f64` `sin`/`cos`/`ln`).

#![forbid(unsafe_code)]

mod rng;

use std::f64::consts::{PI, TAU};

use rng::Rng;
use tonekit_core::{Register, HOP, SAMPLE_RATE};

/// Semitones are measured re this frequency.
const REF_HZ: f64 = 55.0;
/// Harmonics are generated while `h·f0` is below this.
const MAX_HARMONIC_HZ: f64 = 4000.0;
/// ...and f0 counts as at least this for that bound (at most 4 000 harmonics).
const MIN_HARMONIC_F0_HZ: f64 = 1.0;
const RAMP_MS: f64 = 20.0;
/// Unvoiced-onset noise sigma, relative to the voiced peak.
const ONSET_NOISE: f64 = 0.1;
/// Creak noise sigma, relative to the voiced peak.
const CREAK_NOISE: f64 = 0.05;
/// Peak |x| of the finished buffer.
const OUTPUT_PEAK: f64 = 0.5;
/// `n_syllables` of [`register_for`]: well past the cold-start threshold.
const WARM_SYLLABLES: u32 = 100;

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

#[derive(Clone, Debug, PartialEq)]
pub struct Synth {
    /// 16 kHz mono samples, peak |x| = 0.5 (all zeros if nothing was generated).
    pub pcm: Vec<f32>,
    /// `pcm.len()/160 + 1` entries; entry `i` is the f0 at sample `i·160`, `None` if unvoiced.
    pub f0_truth: Vec<Option<f32>>,
    /// Per syllable, half-open `(start_frame, end_frame)`: onset and voiced part, not the gap.
    pub syllable_frames: Vec<(u32, u32)>,
}

fn hz_to_st(hz: f64) -> f64 {
    12.0 * (hz / REF_HZ).log2()
}

fn st_to_hz(st: f64) -> f64 {
    REF_HZ * (st / 12.0).exp2()
}

fn chao_to_hz_f64(chao: f64, floor_hz: f64, ceil_hz: f64) -> f64 {
    let (floor_st, ceil_st) = (hz_to_st(floor_hz), hz_to_st(ceil_hz));
    st_to_hz(floor_st + (chao - 1.0) / 4.0 * (ceil_st - floor_st))
}

/// The pitch at Chao value `chao` for a speaker whose Chao 1 is `floor_hz` and Chao 5 is `ceil_hz`.
///
/// Interpolates in semitones re 55 Hz, so it is the exact inverse of
/// `chao = 1 + 4·(st − floor_st)/(ceil_st − floor_st)`. Unclamped: `chao` may lie outside `1..=5`.
pub fn chao_to_hz(chao: f32, floor_hz: f32, ceil_hz: f32) -> f32 {
    chao_to_hz_f64(f64::from(chao), f64::from(floor_hz), f64::from(ceil_hz)) as f32
}

/// The register of a speaker with the given floor and ceiling, already warm (`n_syllables` = 100).
pub fn register_for(floor_hz: f32, ceil_hz: f32) -> Register {
    let floor_st = hz_to_st(f64::from(floor_hz)) as f32;
    let ceil_st = hz_to_st(f64::from(ceil_hz)) as f32;
    Register {
        floor_st,
        median_st: 0.5 * (floor_st + ceil_st),
        ceil_st,
        n_syllables: WARM_SYLLABLES,
    }
}

/// Chao value at `u` in `0..=1` along `knots` (evenly spaced, linear between them).
fn chao_at(knots: &[f32], u: f64) -> f64 {
    let n = knots.len();
    if n == 1 {
        return f64::from(knots[0]);
    }
    let x = u.clamp(0.0, 1.0) * (n - 1) as f64;
    let i = (x.floor() as usize).min(n - 2);
    let t = x - i as f64;
    f64::from(knots[i]) * (1.0 - t) + f64::from(knots[i + 1]) * t
}

/// Raised-cosine gain at offset `k` samples from an edge; 1 beyond the ramp.
fn ramp_gain(k: usize, ramp: usize) -> f64 {
    if k >= ramp {
        1.0
    } else {
        0.5 * (1.0 - (PI * k as f64 / ramp as f64).cos())
    }
}

/// `sum_{h·f0 < 4 kHz} sin(h·phase)/h`, with f0 taken as at least 1 Hz so that an absurd contour
/// (a Chao value far below the floor maps to nearly 0 Hz) cannot ask for millions of harmonics.
fn harmonic_sum(phase: f64, f0_hz: f64) -> f64 {
    let f0_hz = f0_hz.max(MIN_HARMONIC_F0_HZ);
    let mut acc = 0.0;
    let mut h = 1.0_f64;
    while h * f0_hz < MAX_HARMONIC_HZ {
        acc += (h * phase).sin() / h;
        h += 1.0;
    }
    acc
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

    // --- Noise: onset and creak scale with the voiced peak; one stream, timeline order. ---
    let harmonic_peak = signal.iter().fold(0.0_f64, |m, x| m.max(x.abs()));
    let voiced_peak = if harmonic_peak > 0.0 {
        harmonic_peak
    } else {
        1.0
    };
    let mut rng = Rng::new(spec.seed);
    for place in &placements {
        for x in &mut signal[place.onset.0..place.onset.1] {
            *x = ONSET_NOISE * voiced_peak * rng.gaussian();
        }
        for x in &mut signal[place.creak.0..place.creak.1] {
            *x = CREAK_NOISE * voiced_peak * rng.gaussian();
        }
    }

    // --- Whole-buffer white noise at the requested SNR, re the voiced samples. ---
    if let Some(snr_db) = spec.snr_db {
        let (power, count) = signal
            .iter()
            .zip(&f0_at_sample)
            .filter(|(_, f0)| f0.is_some())
            .fold((0.0_f64, 0_usize), |(p, c), (x, _)| (p + x * x, c + 1));
        if count > 0 {
            let sigma = (power / count as f64).sqrt() / 10.0_f64.powf(f64::from(snr_db) / 20.0);
            for x in &mut signal {
                *x += sigma * rng.gaussian();
            }
        }
    }

    // --- Level and truth. ---
    let peak = signal.iter().fold(0.0_f64, |m, x| m.max(x.abs()));
    let gain = if peak > 0.0 { OUTPUT_PEAK / peak } else { 0.0 };
    let pcm: Vec<f32> = signal.iter().map(|x| (x * gain) as f32).collect();

    let f0_truth = (0..total / HOP + 1)
        .map(|frame| {
            let sample = (frame * HOP).min(total.saturating_sub(1));
            f0_at_sample.get(sample).copied().flatten()
        })
        .collect();

    Synth {
        pcm,
        f0_truth,
        syllable_frames,
    }
}
