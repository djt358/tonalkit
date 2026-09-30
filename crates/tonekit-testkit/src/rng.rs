//! Seeded xorshift64 with Box–Muller Gaussians. Test-only randomness: fast, deterministic and
//! identical everywhere, with no dependency on the `rand` crate.

use std::f64::consts::TAU;

/// Stand-in state for seed 0: xorshift64 is stuck forever at state 0, so 0 must be remapped.
const ZERO_SEED_STATE: u64 = 0x9E37_79B9_7F4A_7C15;

/// Outputs discarded after seeding. Marsaglia's xorshift64 starts weakly from a small state (seed 1
/// first yields ~2^30 of 2^64), so let the state diffuse before the first draw is used.
const WARMUP: usize = 16;

#[derive(Clone, Debug)]
pub(crate) struct Rng {
    state: u64,
    /// Second Box–Muller variate, kept for the next `gaussian` call.
    spare: Option<f64>,
}

impl Rng {
    pub(crate) fn new(seed: u64) -> Self {
        let mut rng = Rng {
            state: if seed == 0 { ZERO_SEED_STATE } else { seed },
            spare: None,
        };
        for _ in 0..WARMUP {
            rng.next_u64();
        }
        rng
    }

    /// Marsaglia xorshift64 (13, 7, 17).
    pub(crate) fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    /// Uniform in `[0, 1)` with 53 random bits.
    pub(crate) fn uniform(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1_u64 << 53) as f64
    }

    /// Standard normal (mean 0, variance 1) by Box–Muller.
    pub(crate) fn gaussian(&mut self) -> f64 {
        if let Some(z) = self.spare.take() {
            return z;
        }
        // 1 - u is in (0, 1], so the logarithm is finite.
        let u1 = 1.0 - self.uniform();
        let u2 = self.uniform();
        let radius = (-2.0 * u1.ln()).sqrt();
        let angle = TAU * u2;
        self.spare = Some(radius * angle.sin());
        radius * angle.cos()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_seed_same_stream_different_seed_different_stream() {
        let draw = |seed| {
            let mut r = Rng::new(seed);
            (0..8).map(|_| r.next_u64()).collect::<Vec<_>>()
        };
        assert_eq!(draw(42), draw(42));
        assert_ne!(draw(42), draw(43));
        assert_ne!(draw(1), draw(2));
    }

    #[test]
    fn seed_zero_is_remapped_and_never_sticks_at_zero() {
        let mut r = Rng::new(0);
        assert_ne!(r.state, 0);
        let xs: Vec<u64> = (0..1000).map(|_| r.next_u64()).collect();
        assert!(xs.iter().all(|x| *x != 0));
        // Seed 0 behaves as the documented constant, not as some other seed.
        let mut c = Rng::new(ZERO_SEED_STATE);
        assert_eq!(xs[0], c.next_u64());
    }

    #[test]
    fn small_seeds_do_not_start_with_tiny_draws() {
        // Without warm-up, seed 1 would give a first uniform of ~6e-11.
        for seed in 1..=20 {
            let mut r = Rng::new(seed);
            let firsts: Vec<f64> = (0..4).map(|_| r.uniform()).collect();
            assert!(firsts.iter().any(|u| *u > 0.01), "seed {seed}: {firsts:?}");
        }
    }

    #[test]
    fn uniform_is_in_unit_interval_with_mean_half() {
        let mut r = Rng::new(9);
        let n = 100_000;
        let xs: Vec<f64> = (0..n).map(|_| r.uniform()).collect();
        assert!(xs.iter().all(|u| (0.0..1.0).contains(u)));
        let mean = xs.iter().sum::<f64>() / n as f64;
        assert!((mean - 0.5).abs() < 0.01, "mean {mean}");
    }

    #[test]
    fn gaussian_has_zero_mean_unit_variance_and_finite_tails() {
        let mut r = Rng::new(3);
        let n = 200_000;
        let xs: Vec<f64> = (0..n).map(|_| r.gaussian()).collect();
        assert!(xs.iter().all(|z| z.is_finite()));
        let mean = xs.iter().sum::<f64>() / n as f64;
        let var = xs.iter().map(|z| (z - mean).powi(2)).sum::<f64>() / n as f64;
        assert!(mean.abs() < 0.01, "mean {mean}");
        assert!((var - 1.0).abs() < 0.02, "var {var}");
        // About 4.6% of a standard normal lies beyond 2 sigma.
        let tail = xs.iter().filter(|z| z.abs() > 2.0).count() as f64 / n as f64;
        assert!((tail - 0.0455).abs() < 0.005, "tail {tail}");
    }
}
