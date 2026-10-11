use std::f64::consts::PI;

use tonekit_core::{EnergyTrack, HOP};

/// Analysis window length in samples (25 ms at 16 kHz).
const WINDOW: usize = 400;
/// Frames quieter than this read as this (digital silence).
const FLOOR_DB: f64 = -100.0;

/// Frame energy in dB: `10 * log10(sum(w^2 x^2) / sum(w^2))` over a 25 ms Hann window centred on
/// each hop and zero-padded past both ends of `pcm`, floored at -100 dB.
///
/// Frame `i` is centred on sample `i * HOP`, so there are `pcm.len() / HOP + 1` frames. The
/// window is periodic (`w[n] = 0.5 - 0.5 cos(2 pi n / 400)`) so its peak lands exactly on the
/// centre sample. A full-scale sine reads -3.0 dB (its mean square is 0.5). Non-finite samples
/// count as silence.
pub fn energy(pcm: &[f32]) -> EnergyTrack {
    let x: Vec<f64> = pcm.iter().map(|&v| finite_or_silence(v)).collect();
    let db = frame_power(&x)
        .into_iter()
        .map(|p| (10.0 * p.log10()).max(FLOOR_DB) as f32)
        .collect();
    EnergyTrack { db }
}

/// A sample as f64, or 0 (silence) if it is not finite.
pub(crate) fn finite_or_silence(v: f32) -> f64 {
    let x = f64::from(v);
    if x.is_finite() {
        x
    } else {
        0.0
    }
}

/// The windowed mean square `sum(w^2 x^2) / sum(w^2)` of `x` around every hop: the 25 ms Hann
/// window of [`energy`], centred on sample `i * HOP` and zero-padded past both ends, one value per
/// frame (`x.len() / HOP + 1`). `x` must be finite.
pub(crate) fn frame_power(x: &[f64]) -> Vec<f64> {
    let w2: Vec<f64> = (0..WINDOW)
        .map(|n| {
            let w = 0.5 - 0.5 * (2.0 * PI * n as f64 / WINDOW as f64).cos();
            w * w
        })
        .collect();
    let norm: f64 = w2.iter().sum();
    let half = WINDOW / 2;

    (0..x.len() / HOP + 1)
        .map(|frame| {
            let centre = frame * HOP;
            // Window offset n reads sample `centre + n - half`; keep 0 <= sample < x.len().
            let first = half.saturating_sub(centre);
            let end = WINDOW.min(x.len() + half - centre);
            let weighted: f64 = (first..end)
                .map(|n| {
                    let v = x[centre + n - half];
                    w2[n] * v * v
                })
                .sum();
            weighted / norm
        })
        .collect()
}
