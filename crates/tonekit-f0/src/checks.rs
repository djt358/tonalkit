use tonekit_core::EnergyTrack;

/// Samples at or above this magnitude count as clipped.
const CLIP_LEVEL: f32 = 0.99;

/// Fraction of samples with `|x| >= 0.99`; 0 for empty input. The `Clipped` issue fires above 1%.
pub fn clipping_ratio(pcm: &[f32]) -> f32 {
    if pcm.is_empty() {
        return 0.0;
    }
    let clipped = pcm.iter().filter(|x| x.abs() >= CLIP_LEVEL).count();
    (clipped as f64 / pcm.len() as f64) as f32
}

/// Dynamic range of the frame energies, `p95 - p10` in dB (percentiles linearly interpolated).
///
/// Speech frames sit near p95 and the noise floor near p10, so this stands in for SNR. The
/// `LowSnr` issue fires below 10 dB. Non-finite frames are ignored; fewer than two usable frames
/// give 0.
pub fn snr_db(e: &EnergyTrack) -> f32 {
    let mut db: Vec<f32> = e.db.iter().copied().filter(|d| d.is_finite()).collect();
    if db.len() < 2 {
        return 0.0;
    }
    db.sort_by(f32::total_cmp);
    (percentile(&db, 0.95) - percentile(&db, 0.10)) as f32
}

/// `q`-quantile (0..=1) of a sorted, non-empty slice, interpolating linearly between ranks.
fn percentile(sorted: &[f32], q: f64) -> f64 {
    let rank = q * (sorted.len() - 1) as f64;
    let below = rank.floor() as usize;
    let above = (below + 1).min(sorted.len() - 1);
    let lo = f64::from(sorted[below]);
    let hi = f64::from(sorted[above]);
    lo + (rank - below as f64) * (hi - lo)
}
