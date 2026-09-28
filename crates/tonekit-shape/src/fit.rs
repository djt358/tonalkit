//! Least-squares fits and the turning-point rule (controller ruling R4).

/// Slope of the least-squares line through `(x, y)` points; 0 when the x values do not vary.
pub(crate) fn line_slope(points: &[(f64, f64)]) -> f64 {
    let n = points.len() as f64;
    let mx = points.iter().map(|p| p.0).sum::<f64>() / n;
    let my = points.iter().map(|p| p.1).sum::<f64>() / n;
    let sxx: f64 = points.iter().map(|p| (p.0 - mx) * (p.0 - mx)).sum();
    let sxy: f64 = points.iter().map(|p| (p.0 - mx) * (p.1 - my)).sum();
    if sxx > 0.0 {
        sxy / sxx
    } else {
        0.0
    }
}

/// The coefficient `a` of the least-squares quadratic `a·x² + b·x + c` through `(x, y)` points;
/// 0 when the points do not determine a parabola (fewer than three distinct x values).
pub(crate) fn quadratic_coefficient(points: &[(f64, f64)]) -> f64 {
    // `a` does not depend on where x is measured from, so centre x for conditioning.
    let n = points.len() as f64;
    let mx = points.iter().map(|p| p.0).sum::<f64>() / n;
    let mut s = [0.0_f64; 5]; // Σ x^0 .. Σ x^4
    let mut t = [0.0_f64; 3]; // Σ y, Σ x·y, Σ x²·y
    for &(x, y) in points {
        let x = x - mx;
        let mut pow = 1.0;
        for (k, sk) in s.iter_mut().enumerate() {
            *sk += pow;
            if k < 3 {
                t[k] += pow * y;
            }
            pow *= x;
        }
    }
    // Normal equations for (a, b, c).
    let mut m = [
        [s[4], s[3], s[2], t[2]],
        [s[3], s[2], s[1], t[1]],
        [s[2], s[1], s[0], t[0]],
    ];
    // Gaussian elimination with partial pivoting.
    for col in 0..3 {
        let pivot = (col..3)
            .max_by(|&i, &j| m[i][col].abs().total_cmp(&m[j][col].abs()))
            .unwrap_or(col);
        if m[pivot][col].abs() < 1e-12 {
            return 0.0;
        }
        m.swap(col, pivot);
        let pivot_row = m[col];
        for row in m.iter_mut().skip(col + 1) {
            let f = row[col] / pivot_row[col];
            for (cell, p) in row.iter_mut().zip(pivot_row).skip(col) {
                *cell -= f * p;
            }
        }
    }
    // Back-substitute for `a` (the first unknown) only.
    let c = m[2][3] / m[2][2];
    let b = (m[1][3] - m[1][2] * c) / m[1][1];
    (m[0][3] - m[0][2] * c - m[0][1] * b) / m[0][0]
}

/// A turning point must lie strictly inside this fraction range of the voiced part.
const TURN_INTERIOR: (f64, f64) = (0.1, 0.9);
/// ...and stand out from both endpoints by at least this many Chao.
const TURN_MIN_EXCURSION: f64 = 0.5;
/// Values this close to an extremum count as the same plateau.
const PLATEAU_EPS: f64 = 1e-9;

/// The centre of the plateau of extreme values of `curve` (maxima when `sign` is 1, minima when
/// it is −1), as `(value, index)`. `curve` must not be empty.
fn extremum(curve: &[f64], sign: f64) -> (f64, f64) {
    let best = curve
        .iter()
        .map(|v| sign * v)
        .fold(f64::NEG_INFINITY, f64::max);
    let near = |v: &f64| sign * v >= best - PLATEAU_EPS;
    let first = curve.iter().position(near).unwrap_or(0);
    let last = curve.iter().rposition(near).unwrap_or(first);
    (sign * best, 0.5 * (first + last) as f64)
}

/// Where in the voiced part (0..1) the curve turns, if it does.
///
/// `smoothed_chao` is the 3-frame-smoothed voiced curve in Chao units, one entry per frame of the
/// voiced part. Its interior minimum (or maximum) is a turning point if it lies in (0.1, 0.9) and
/// is at least 0.5 Chao below (above) both endpoints. If both qualify, the larger excursion,
/// measured from the nearer endpoint, wins.
pub(crate) fn turning_point(smoothed_chao: &[f64]) -> Option<f32> {
    let n = smoothed_chao.len();
    if n < 3 {
        return None;
    }
    let (first, last) = (smoothed_chao[0], smoothed_chao[n - 1]);
    let position = |index: f64| index / (n - 1) as f64;
    let candidates = [
        // (excursion beyond the nearer endpoint, position) for the minimum, then the maximum.
        {
            let (v, i) = extremum(smoothed_chao, -1.0);
            ((first - v).min(last - v), position(i))
        },
        {
            let (v, i) = extremum(smoothed_chao, 1.0);
            ((v - first).min(v - last), position(i))
        },
    ];
    candidates
        .into_iter()
        .filter(|&(excursion, u)| {
            excursion >= TURN_MIN_EXCURSION && u > TURN_INTERIOR.0 && u < TURN_INTERIOR.1
        })
        .max_by(|a, b| a.0.total_cmp(&b.0))
        .map(|(_, u)| u as f32)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-9
    }

    #[test]
    fn line_recovers_slope_and_is_shift_invariant() {
        let pts: Vec<(f64, f64)> = (0..20)
            .map(|i| (i as f64 * 0.01, 3.0 - 7.5 * i as f64 * 0.01))
            .collect();
        assert!(close(line_slope(&pts), -7.5));
        // Repeated x only: no slope to speak of.
        assert_eq!(line_slope(&[(1.0, 2.0), (1.0, 5.0)]), 0.0);
    }

    #[test]
    fn quadratic_recovers_a_exactly() {
        let pts: Vec<(f64, f64)> = (0..30)
            .map(|i| {
                let u = i as f64 / 29.0;
                (u, 4.0 * u * u - 3.0 * u + 1.5)
            })
            .collect();
        assert!(close(quadratic_coefficient(&pts), 4.0));
        // A straight line has none.
        let line: Vec<(f64, f64)> = (0..30)
            .map(|i| (i as f64 / 29.0, 2.0 * i as f64 / 29.0))
            .collect();
        assert!(quadratic_coefficient(&line).abs() < 1e-9);
        // Exactly three points determine it.
        assert!(close(
            quadratic_coefficient(&[(0.0, 1.0), (0.5, 0.0), (1.0, 1.0)]),
            4.0
        ));
        // Fewer than three distinct x values do not.
        assert_eq!(
            quadratic_coefficient(&[(0.0, 1.0), (0.0, 2.0), (1.0, 3.0)]),
            0.0
        );
    }

    #[test]
    fn turning_point_examples() {
        let dip = [3.0, 2.0, 1.0, 2.0, 3.0];
        assert_eq!(turning_point(&dip), Some(0.5));
        let peak = [1.0, 2.0, 3.0, 2.0, 1.0];
        assert_eq!(turning_point(&peak), Some(0.5));
        assert_eq!(turning_point(&[1.0, 2.0, 3.0, 4.0, 5.0]), None);
        assert_eq!(turning_point(&[3.0, 3.0, 3.0, 3.0]), None);
        assert_eq!(turning_point(&[1.0, 5.0]), None);
        // Exactly half a Chao beyond both endpoints qualifies; a hair less does not.
        assert_eq!(turning_point(&[2.0, 1.5, 2.0]), Some(0.5));
        assert_eq!(turning_point(&[2.0, 1.51, 2.0]), None);
    }

    #[test]
    fn plateau_turning_point_is_centred() {
        let flat_bottom = [3.0, 1.0, 1.0, 1.0, 3.0, 3.0, 3.0];
        let u = turning_point(&flat_bottom).unwrap();
        assert!((u - 2.0 / 6.0).abs() < 1e-6, "u {u}");
    }

    #[test]
    fn interior_bounds_are_open() {
        // Minimum exactly at u = 0.1 (index 1 of 11) is excluded; at index 2 (0.2) is kept.
        let mut c = vec![3.0; 11];
        c[1] = 1.0;
        assert_eq!(turning_point(&c), None);
        let mut c = vec![3.0; 11];
        c[2] = 1.0;
        assert!(turning_point(&c).is_some());
        let mut c = vec![3.0; 11];
        c[9] = 1.0;
        assert_eq!(turning_point(&c), None);
    }
}
