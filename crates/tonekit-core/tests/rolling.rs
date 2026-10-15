//! The rolling register's types (ruling R111): serde round trips, the field names other
//! languages see, and which parameters and pools are usable.

use tonekit_core::{Register, RollingParams, RollingRegister, POOL_BINS, POOL_BIN_ST, POOL_LO_ST};

fn rolling() -> RollingRegister {
    let mut pool = vec![0.0; POOL_BINS];
    pool[200] = 0.123_456_789_012_345_67;
    pool[201] = 1e-5;
    pool[260] = 3.5;
    RollingRegister {
        register: Register {
            floor_st: 14.05,
            median_st: 20.0,
            ceil_st: 26.1,
            n_syllables: 42,
        },
        pool,
    }
}

#[test]
fn a_rolling_register_round_trips_exactly() {
    let r = rolling();
    let text = serde_json::to_string(&r).unwrap();
    let back: RollingRegister = serde_json::from_str(&text).unwrap();
    assert_eq!(back, r);
    // Bit for bit: the pool is f64 and JSON keeps every bit of it.
    assert!(back
        .pool
        .iter()
        .zip(&r.pool)
        .all(|(a, b)| a.to_bits() == b.to_bits()));
    let v: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(v["register"]["n_syllables"], 42);
    assert_eq!(v["pool"].as_array().unwrap().len(), POOL_BINS);
}

#[test]
fn parameters_round_trip_with_null_for_none() {
    for p in [
        RollingParams::DEFAULT,
        RollingParams::POOLED,
        RollingParams {
            half_life_s: Some(12.5),
            max_share: None,
        },
    ] {
        let text = serde_json::to_string(&p).unwrap();
        assert_eq!(serde_json::from_str::<RollingParams>(&text).unwrap(), p);
    }
    assert_eq!(
        serde_json::to_string(&RollingParams::POOLED).unwrap(),
        r#"{"half_life_s":null,"max_share":null}"#
    );
}

#[test]
fn the_grid_covers_every_pitch_pyin_reports() {
    let top = POOL_LO_ST + POOL_BINS as f32 * POOL_BIN_ST;
    // pYIN tracks 50 to 600 Hz: about -1.6 to 41.4 semitones re 55 Hz.
    assert!(POOL_LO_ST < -1.7 && top > 41.5, "{POOL_LO_ST}..{top}");
    assert!((top - 48.0).abs() < 1e-3);
}

#[test]
fn which_parameters_are_usable() {
    assert_eq!(RollingParams::DEFAULT.problem(), None);
    assert_eq!(RollingParams::POOLED.problem(), None);
    assert_eq!(RollingParams::default(), RollingParams::DEFAULT);
    for (p, says) in [
        ((Some(0.0), None), "half_life_s"),
        ((Some(f32::INFINITY), None), "half_life_s"),
        ((Some(f32::NAN), Some(0.03)), "half_life_s"),
        ((Some(30.0), Some(0.0)), "max_share"),
        ((Some(30.0), Some(1.0)), "max_share"),
        ((Some(30.0), Some(f32::NAN)), "max_share"),
        ((None, Some(0.03)), "needs a half_life_s"),
    ] {
        let params = RollingParams {
            half_life_s: p.0,
            max_share: p.1,
        };
        let problem = params.problem().unwrap_or_default();
        assert!(problem.contains(says), "{params:?}: {problem:?}");
    }
}

#[test]
fn which_pools_are_usable() {
    assert!(rolling().pool_usable());
    let mut r = rolling();
    r.pool.push(0.0);
    assert!(!r.pool_usable());
    let mut r = rolling();
    r.pool[7] = -1e-9;
    assert!(!r.pool_usable());
    let mut r = rolling();
    r.pool[7] = f64::INFINITY;
    assert!(!r.pool_usable());
}
