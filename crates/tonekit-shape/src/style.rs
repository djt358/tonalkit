//! Fitting an individual's style (imprint) from decoded syllable shapes (spec §6.3).

use tonekit_core::{AccentId, StyleProfile, StyleTone, ToneId, ToneShape};

/// Running per-tone totals for the pointwise mean.
struct Acc {
    tone: ToneId,
    n: u32,
    /// Per contour point: sum and number of shapes that have that point.
    points: Vec<(f64, u32)>,
}

/// Per-tone mean contours (in the speaker's own normalised Chao space) and the mean range.
///
/// Tones appear in first-seen order; `n` counts the shapes behind each. `mean_range` is the mean
/// of `range` over all fits, or 0 when there are none.
pub fn fit_style(accent: AccentId, fits: &[(ToneId, ToneShape)]) -> StyleProfile {
    let mut accs: Vec<Acc> = Vec::new();
    let mut range_sum = 0.0_f64;
    for (tone, shape) in fits {
        range_sum += f64::from(shape.range);
        let i = match accs.iter().position(|a| &a.tone == tone) {
            Some(i) => i,
            None => {
                accs.push(Acc {
                    tone: tone.clone(),
                    n: 0,
                    points: Vec::new(),
                });
                accs.len() - 1
            }
        };
        let acc = &mut accs[i];
        acc.n += 1;
        if acc.points.len() < shape.contour.len() {
            acc.points.resize(shape.contour.len(), (0.0, 0));
        }
        for (slot, &c) in acc.points.iter_mut().zip(&shape.contour) {
            slot.0 += f64::from(c);
            slot.1 += 1;
        }
    }
    StyleProfile {
        accent,
        tones: accs
            .into_iter()
            .map(|a| StyleTone {
                tone: a.tone,
                contour: a
                    .points
                    .iter()
                    .map(|&(sum, count)| (sum / f64::from(count)) as f32)
                    .collect(),
                n: a.n,
            })
            .collect(),
        mean_range: if fits.is_empty() {
            0.0
        } else {
            (range_sum / fits.len() as f64) as f32
        },
    }
}
