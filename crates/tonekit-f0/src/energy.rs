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
    let w2: Vec<f64> = (0..WINDOW)
        .map(|n| {
            let w = 0.5 - 0.5 * (2.0 * PI * n as f64 / WINDOW as f64).cos();
            w * w
        })
        .collect();
    let norm: f64 = w2.iter().sum();
    let half = WINDOW / 2;

    let db = (0..pcm.len() / HOP + 1)
        .map(|frame| {
            let centre = frame * HOP;
            // Window offset n reads sample `centre + n - half`; keep 0 <= sample < pcm.len().
            let first = half.saturating_sub(centre);
            let end = WINDOW.min(pcm.len() + half - centre);
            let weighted: f64 = (first..end)
                .map(|n| {
                    let x = f64::from(pcm[centre + n - half]);
                    if x.is_finite() {
                        w2[n] * x * x
                    } else {
                        0.0
                    }
                })
                .sum();
            (10.0 * (weighted / norm).log10()).max(FLOOR_DB) as f32
        })
        .collect();
    EnergyTrack { db }
}
