//! Parameter-aligned feedback (spec §7.1, "Deltas"): how the syllable differs from the best
//! matching target component in the terms a learner can act on ("start higher", "turn earlier").
//!
//! Four candidate differences are measured in units of the component's tolerance (`z`): onset,
//! offset, turning-point time and range. Those beyond one σ are kept, the two largest by `|z|`.
//! The σ are widened exactly as they are for scoring, so a measurement issue that loosens the
//! likelihood loosens the advice too. For a syllable too short to trust its interior (`TooShort`,
//! ruling R26, spec §12) only the onset and offset are compared: turning-point time and range are
//! read off the contour and are not offered.

use tonekit_core::{DeltaKind, ShapeDelta, ToneShape};

use crate::Component;

/// A difference speaks only when it exceeds this many σ.
const MIN_Z: f64 = 1.0;
/// At most this many deltas are returned.
const KEEP: usize = 2;

/// A turning point lies strictly inside this fraction range of the syllable...
const TURN_INTERIOR: (f64, f64) = (0.1, 0.9);
/// ...and stands out from both endpoints by at least this many Chao (ruling R4).
const TURN_MIN_EXCURSION: f64 = 0.5;
/// Values this close to an extremum count as the same plateau.
const PLATEAU_EPS: f64 = 1e-9;

/// The advice for shape `x` against its best-matching component `c`, most significant first.
///
/// `widen` is the tolerance widening for the analysis's issues (`crate::widen_for`). With
/// `endpoints_only` (the shape is `TooShort`) only `Start*` and `End*` deltas are considered. A
/// candidate whose z-score or amount is not finite (a NaN range, an infinite duration) is skipped.
pub(crate) fn compute(
    x: &ToneShape,
    c: &Component,
    widen: f64,
    endpoints_only: bool,
) -> Vec<ShapeDelta> {
    let sigma = |v: f32| f64::from(v) * widen;

    // (|z|, kind, amount); at most four candidates, kept on the stack.
    let mut found = [(0.0f64, DeltaKind::StartHigher, 0.0f32); 4];
    let mut n = 0;
    let mut offer = |z: f64, kind: DeltaKind, amount: f64| {
        let amount = amount as f32;
        if z.is_finite() && z.abs() > MIN_Z && amount.is_finite() {
            found[n] = (z.abs(), kind, amount);
            n += 1;
        }
    };

    // Onset and offset: the syllable that starts lower than expected should "start higher".
    let d_on = f64::from(x.onset) - f64::from(c.onset);
    offer(
        d_on / sigma(c.sigma.onset),
        if d_on < 0.0 {
            DeltaKind::StartHigher
        } else {
            DeltaKind::StartLower
        },
        d_on.abs(),
    );
    let d_off = f64::from(x.offset) - f64::from(c.offset);
    offer(
        d_off / sigma(c.sigma.offset),
        if d_off < 0.0 {
            DeltaKind::EndHigher
        } else {
            DeltaKind::EndLower
        },
        d_off.abs(),
    );

    if !endpoints_only {
        // Turning-point time, only when both have one: later than expected means "turn earlier".
        if let (Some(xu), Some(cu)) = (x.turning_point, turning_point(&c.contour)) {
            let du = f64::from(xu) - cu;
            offer(
                du / sigma(c.sigma.turning_point),
                if du > 0.0 {
                    DeltaKind::TurnEarlier
                } else {
                    DeltaKind::TurnLater
                },
                du.abs() * f64::from(x.duration_ms),
            );
        }

        // Range: a narrower syllable than expected should be "wider".
        let (lo, hi) = c
            .contour
            .iter()
            .fold((f64::INFINITY, f64::NEG_INFINITY), |(lo, hi), &v| {
                (lo.min(f64::from(v)), hi.max(f64::from(v)))
            });
        let d_range = f64::from(x.range) - (hi - lo);
        offer(
            d_range / sigma(c.sigma.contour),
            if d_range < 0.0 {
                DeltaKind::WiderRange
            } else {
                DeltaKind::NarrowerRange
            },
            d_range.abs(),
        );
    }

    // Stable, so equal |z| keep the order onset, offset, turn, range.
    found[..n].sort_by(|a, b| b.0.total_cmp(&a.0));
    found[..n.min(KEEP)]
        .iter()
        .map(|&(_, kind, amount)| ShapeDelta { kind, amount })
        .collect()
}

/// Where in the syllable (0..1) `contour` turns, by the rule shape extraction applies (ruling R4):
/// the interior minimum or maximum, if it lies in (0.1, 0.9) and stands at least 0.5 Chao beyond
/// both endpoints. If both qualify, the larger excursion, measured from the nearer endpoint, wins.
/// A plateau of equal extreme values is centred.
fn turning_point(contour: &[f32]) -> Option<f64> {
    let n = contour.len();
    if n < 3 {
        return None;
    }
    let (first, last) = (f64::from(contour[0]), f64::from(contour[n - 1]));
    let position = |index: f64| index / (n - 1) as f64;
    let extremum = |sign: f64| {
        let best = contour
            .iter()
            .map(|&v| sign * f64::from(v))
            .fold(f64::NEG_INFINITY, f64::max);
        let near = |v: &f32| sign * f64::from(*v) >= best - PLATEAU_EPS;
        let a = contour.iter().position(near).unwrap_or(0);
        let b = contour.iter().rposition(near).unwrap_or(a);
        (sign * best, position(0.5 * (a + b) as f64))
    };
    let (vmin, umin) = extremum(-1.0);
    let (vmax, umax) = extremum(1.0);
    [
        ((first - vmin).min(last - vmin), umin),
        ((vmax - first).min(vmax - last), umax),
    ]
    .into_iter()
    .filter(|&(excursion, u)| {
        excursion >= TURN_MIN_EXCURSION && u > TURN_INTERIOR.0 && u < TURN_INTERIOR.1
    })
    .max_by(|a, b| a.0.total_cmp(&b.0))
    .map(|(_, u)| u)
}

#[cfg(test)]
mod tests {
    use super::turning_point;

    #[test]
    fn turning_point_follows_the_extraction_rule() {
        // Same cases as tonekit-shape's fit tests, on unsmoothed contours.
        let c = turning_point;
        assert_eq!(c(&[2.0, 1.0, 2.0]), Some(0.5));
        assert_eq!(c(&[2.0, 4.0, 2.0]), Some(0.5));
        assert_eq!(c(&[1.0, 2.0, 3.0, 4.0, 5.0]), None);
        assert_eq!(c(&[3.0, 3.0, 3.0, 3.0]), None);
        assert_eq!(c(&[1.0, 5.0]), None);
        assert_eq!(c(&[2.0, 1.5, 2.0]), Some(0.5)); // exactly 0.5 beyond both: counts
        assert_eq!(c(&[2.0, 1.51, 2.0]), None);
        // A flat bottom is centred.
        let flat = [3.0, 1.0, 1.0, 1.0, 1.0, 3.0];
        assert_eq!(c(&flat), Some(0.5));
        // The extremum must be interior (0.1, 0.9): a late dip at u = 0.9 is not.
        let late = [3.0f32, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 1.0, 3.0];
        assert_eq!(c(&late), None);
        // Both a dip and a peak qualify: the larger excursion wins.
        let both = [3.0, 2.0, 3.0, 5.0, 3.0, 3.0];
        assert_eq!(c(&both), Some(3.0 / 5.0)); // the peak at index 3 stands 2 above; the dip 1
    }
}
