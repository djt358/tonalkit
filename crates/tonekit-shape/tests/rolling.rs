//! The rolling register (ruling R111) and its lite form (ruling R120) on simulated speakers: they
//! follow a learner whose register settles, one odd utterance moves them only a bounded amount,
//! and they are deterministic.

use tonekit_core::{Register, RollingParams, RollingRegister, POOL_BINS};
use tonekit_shape::{
    cold_register, merge_register, roll_register, roll_register_lite, utterance_cap_s,
};
use tonekit_testkit::Rng;

/// Standard normal quantiles: at 0.95, and at 0.95 / (1 − 0.032), where a pool's p95 can go
/// when one utterance holds 3.2% of it and lies wholly above (and, mirrored, its p5 below).
const Z_95: f64 = 1.644_854;
const Z_BOUND: f64 = 2.083_671;

/// One utterance's speech-only voiced semitones: `frames` draws from N(`mean`, `sd`).
fn utterance(rng: &mut Rng, frames: usize, mean: f64, sd: f64) -> Vec<f32> {
    (0..frames)
        .map(|_| (mean + sd * rng.gaussian()) as f32)
        .collect()
}

/// A learner's true register at one moment: the p5, p50 and p95 of N(`mean`, `sd`).
fn truth(mean: f64, sd: f64) -> [f64; 3] {
    [mean - Z_95 * sd, mean, mean + Z_95 * sd]
}

/// The largest error of floor, median or ceiling against the truth.
fn error(r: &Register, want: [f64; 3]) -> f64 {
    [r.floor_st, r.median_st, r.ceil_st]
        .iter()
        .zip(want)
        .map(|(&got, want)| (f64::from(got) - want).abs())
        .fold(0.0, f64::max)
}

fn roll(r: Option<&RollingRegister>, frames: &[f32], params: &RollingParams) -> RollingRegister {
    roll_register(r, frames, 3, params)
}

/// The settled learner: mean 20 st (≈ 175 Hz), sd 2.5 st. At the start they speak 3 st higher
/// and 60% more variably, settling linearly over `SETTLE` phrases.
const SETTLED: (f64, f64) = (20.0, 2.5);
const START: (f64, f64) = (23.0, 4.0);
const SETTLE: usize = 40;
const AFTER: usize = 150;
/// 0.6 s of voiced speech per three-syllable phrase; the drill's syllables are drawn out.
const PHRASE_FRAMES: usize = 60;
const DRILL_FRAMES: usize = 150;

fn state(k: usize) -> (f64, f64) {
    let s = 1.0 - (k.min(SETTLE) as f64 / SETTLE as f64);
    (
        SETTLED.0 + s * (START.0 - SETTLED.0),
        SETTLED.1 + s * (START.1 - SETTLED.1),
    )
}

struct Tracks {
    /// Per phrase after the drill: the error of the register it was graded with.
    rolling: Vec<f64>,
    pooled: Vec<f64>,
    drill: Vec<f64>,
    /// The lite register under the same parameters (ruling R120), and today's merge
    /// (`register_update`, which is the lite register with no decay or cap).
    lite: Vec<f64>,
    merged: Vec<f64>,
}

/// The drill (8 utterances in the starting state), then the phrases. Each phrase is graded with
/// the register built from the drill and the phrases before it, then rolled in.
fn simulate(params: &RollingParams) -> Tracks {
    let mut rng = Rng::new(11);
    let mut rolling: Option<RollingRegister> = None;
    let mut pooled: Option<RollingRegister> = None;
    let mut lite: Option<Register> = None;
    let mut merged: Option<Register> = None;
    for _ in 0..8 {
        let frames = utterance(&mut rng, DRILL_FRAMES, START.0, START.1);
        rolling = Some(roll_register(rolling.as_ref(), &frames, 4, params));
        pooled = Some(roll_register(
            pooled.as_ref(),
            &frames,
            4,
            &RollingParams::POOLED,
        ));
        lite = Some(roll_register_lite(lite.as_ref(), &frames, 4, params));
        merged = Some(roll_register_lite(
            merged.as_ref(),
            &frames,
            4,
            &RollingParams::POOLED,
        ));
    }
    let drill = pooled.clone().unwrap().register;
    let mut tracks = Tracks {
        rolling: Vec::new(),
        pooled: Vec::new(),
        drill: Vec::new(),
        lite: Vec::new(),
        merged: Vec::new(),
    };
    for k in 0..SETTLE + AFTER {
        let (mean, sd) = state(k);
        let want = truth(mean, sd);
        tracks
            .rolling
            .push(error(&rolling.as_ref().unwrap().register, want));
        tracks
            .pooled
            .push(error(&pooled.as_ref().unwrap().register, want));
        tracks.drill.push(error(&drill, want));
        tracks.lite.push(error(lite.as_ref().unwrap(), want));
        tracks.merged.push(error(merged.as_ref().unwrap(), want));
        let frames = utterance(&mut rng, PHRASE_FRAMES, mean, sd);
        rolling = Some(roll(rolling.as_ref(), &frames, params));
        pooled = Some(roll(pooled.as_ref(), &frames, &RollingParams::POOLED));
        lite = Some(roll_register_lite(lite.as_ref(), &frames, 3, params));
        merged = Some(roll_register_lite(
            merged.as_ref(),
            &frames,
            3,
            &RollingParams::POOLED,
        ));
    }
    tracks
}

fn mean(v: &[f64]) -> f64 {
    v.iter().sum::<f64>() / v.len() as f64
}

#[test]
fn the_rolling_register_follows_a_learner_who_settles() {
    let t = simulate(&RollingParams::DEFAULT);
    // 150 settled phrases are 90 s of speech: three half-lives of the default 30 s.
    let n = t.rolling.len();
    let settling = mean(&t.rolling[SETTLE..SETTLE + 20]);
    let late = mean(&t.rolling[n - 20..]);
    // Rolling: the error shrinks once the learner has settled, to well under a semitone.
    assert!(
        late < 0.5 * settling,
        "rolling: {settling:.2} then {late:.2}"
    );
    assert!(late < 0.6, "rolling ends {late:.2} st off");
    // Pooling every frame lags: the nervous start never leaves the pool.
    let pooled = mean(&t.pooled[n - 20..]);
    assert!(
        pooled > 2.0 * late && pooled > 0.6,
        "pooled {pooled:.2} vs rolling {late:.2}"
    );
    // The drill alone is wrong by about the 3 st shift (and the extra width) once they settle.
    let drill = mean(&t.drill[n - 20..]);
    assert!(drill > 2.5, "drill {drill:.2}");
}

#[test]
fn a_shorter_half_life_follows_faster() {
    let fast = RollingParams {
        half_life_s: Some(10.0),
        max_share: Some(0.03),
    };
    let slow = RollingParams {
        half_life_s: Some(90.0),
        max_share: Some(0.03),
    };
    let window = SETTLE + 10..SETTLE + 40;
    let fast = mean(&simulate(&fast).rolling[window.clone()]);
    let slow = mean(&simulate(&slow).rolling[window]);
    assert!(fast < slow, "fast {fast:.2} slow {slow:.2}");
}

/// A pool that has heard `n` phrases of the settled speaker, under `params`.
fn settled_pool(rng: &mut Rng, n: usize, params: &RollingParams) -> RollingRegister {
    let mut r = None;
    for _ in 0..n {
        let frames = utterance(rng, PHRASE_FRAMES, SETTLED.0, SETTLED.1);
        r = Some(roll(r.as_ref(), &frames, params));
    }
    r.unwrap()
}

#[test]
fn one_odd_utterance_moves_a_full_register_by_a_bounded_amount() {
    let params = RollingParams {
        half_life_s: Some(30.0),
        max_share: Some(0.03),
    };
    let mut rng = Rng::new(5);
    // 300 phrases: 180 s of speech, six half-lives, so the pool is full.
    let before = settled_pool(&mut rng, 300, &params);
    let full: f64 = before.pool.iter().sum();
    let cap = utterance_cap_s(&params).unwrap();
    // The share the capped utterance takes of the pool it joins (about 3.1%). The pool is
    // N(20, 2.5) whatever the decay, so with that share its p95 can rise to the 0.95 / (1 −
    // share) quantile at most, and its p5 fall to the mirror image: about 1.1 st.
    let share = cap / (full * (-cap / 30.0).exp2() + cap);
    assert!(share < 0.032, "share {share}");
    let bound = (SETTLED.1 * (Z_BOUND - Z_95) + 0.15) as f32; // + sampling and the 0.1 st grid

    // A 5 s shout an octave up, a 5 s creaky run 15 st down.
    let shout = utterance(&mut rng, 500, SETTLED.0 + 12.0, 1.0);
    let creak = utterance(&mut rng, 500, SETTLED.0 - 15.0, 1.0);
    let b = &before.register;
    let after = roll(Some(&before), &shout, &params).register;
    assert!(
        after.ceil_st - b.ceil_st < bound,
        "{b:?} -> {after:?} (bound {bound:.2})"
    );
    assert!((after.median_st - b.median_st).abs() < 0.2);
    assert!((after.floor_st - b.floor_st).abs() < 0.2);
    let after = roll(Some(&before), &creak, &params).register;
    assert!(
        b.floor_st - after.floor_st < bound,
        "{b:?} -> {after:?} (bound {bound:.2})"
    );
    assert!((after.median_st - b.median_st).abs() < 0.2);
    assert!((after.ceil_st - b.ceil_st).abs() < 0.2);
}

#[test]
fn a_capped_utterance_does_not_flush_the_pool() {
    let params = RollingParams::DEFAULT;
    let mut rng = Rng::new(9);
    let before = settled_pool(&mut rng, 300, &params);
    let full: f64 = before.pool.iter().sum();
    // A 20 s monologue counts as the cap, and the pool decays by that much only.
    let long = utterance(&mut rng, 2000, SETTLED.0, SETTLED.1);
    let after = roll(Some(&before), &long, &params);
    let cap = utterance_cap_s(&params).unwrap();
    let total: f64 = after.pool.iter().sum();
    let want = full * (-cap / f64::from(params.half_life_s.unwrap())).exp2() + cap;
    assert!((total - want).abs() < 1e-6, "{total} vs {want}");
}

#[test]
fn the_cap_is_the_share_of_a_full_pool() {
    let cap = utterance_cap_s(&RollingParams::DEFAULT).unwrap();
    // −30 · log2(0.97) ≈ 1.32 s: about 3% of the 30 / ln 2 ≈ 43 s a full pool holds.
    assert!((cap - 1.318).abs() < 1e-3, "{cap}");
    assert_eq!(utterance_cap_s(&RollingParams::POOLED), None);
    let no_cap = RollingParams {
        half_life_s: Some(30.0),
        max_share: None,
    };
    assert_eq!(utterance_cap_s(&no_cap), None);
}

#[test]
fn rolling_is_deterministic() {
    let mut a = Rng::new(3);
    let mut b = Rng::new(3);
    let x = settled_pool(&mut a, 50, &RollingParams::DEFAULT);
    let y = settled_pool(&mut b, 50, &RollingParams::DEFAULT);
    assert_eq!(x, y);
    let bits = |r: &RollingRegister| r.pool.iter().map(|w| w.to_bits()).collect::<Vec<_>>();
    assert_eq!(bits(&x), bits(&y));
}

#[test]
fn an_utterance_with_nothing_measured_teaches_nothing() {
    let mut rng = Rng::new(4);
    let before = settled_pool(&mut rng, 10, &RollingParams::DEFAULT);
    let frames = utterance(&mut rng, 80, 30.0, 1.0);
    assert_eq!(
        roll_register(Some(&before), &frames, 0, &RollingParams::DEFAULT),
        before
    );
    // From nothing, nothing: the fallback register counting no syllables.
    let empty = roll_register(None, &frames, 0, &RollingParams::DEFAULT);
    assert_eq!(empty.register.n_syllables, 0);
    assert_eq!(empty.pool, vec![0.0; POOL_BINS]);
}

#[test]
fn measured_syllables_without_pitch_only_count() {
    let mut rng = Rng::new(6);
    let before = settled_pool(&mut rng, 5, &RollingParams::DEFAULT);
    let after = roll_register(Some(&before), &[f32::NAN], 2, &RollingParams::DEFAULT);
    assert_eq!(after.pool, before.pool);
    assert_eq!(after.register.n_syllables, before.register.n_syllables + 2);
}

#[test]
fn an_unusable_pool_starts_afresh() {
    let mut rng = Rng::new(8);
    let frames = utterance(&mut rng, 80, 18.0, 2.0);
    let fresh = roll_register(None, &frames, 3, &RollingParams::DEFAULT);
    let mut broken = settled_pool(&mut rng, 5, &RollingParams::DEFAULT);
    broken.pool[3] = f64::NAN;
    assert_eq!(
        roll_register(Some(&broken), &frames, 3, &RollingParams::DEFAULT),
        fresh
    );
    broken.pool.truncate(10);
    assert_eq!(
        roll_register(Some(&broken), &frames, 3, &RollingParams::DEFAULT),
        fresh
    );
}

#[test]
fn pitches_off_the_grid_count_in_the_end_bins_and_the_register_stays_usable() {
    let frames = [-40.0_f32, 100.0, 20.0, 21.0];
    let r = roll_register(None, &frames, 40, &RollingParams::POOLED);
    assert!(r.pool[0] > 0.0 && r.pool[POOL_BINS - 1] > 0.0);
    let g = &r.register;
    assert!(
        g.floor_st >= -6.0 && g.ceil_st <= 48.0 && g.floor_st < g.ceil_st,
        "{g:?}"
    );
}

// ---- the lite register (ruling R120) ------------------------------------------------------------

/// A lite register that has heard `n` phrases of the settled speaker, under `params`.
fn settled_lite(rng: &mut Rng, n: usize, params: &RollingParams) -> Register {
    let mut r = None;
    for _ in 0..n {
        let frames = utterance(rng, PHRASE_FRAMES, SETTLED.0, SETTLED.1);
        r = Some(roll_register_lite(r.as_ref(), &frames, 3, params));
    }
    r.unwrap()
}

#[test]
fn the_lite_register_follows_a_learner_who_settles() {
    let t = simulate(&RollingParams::DEFAULT);
    let n = t.lite.len();
    let settling = mean(&t.lite[SETTLE..SETTLE + 20]);
    let late = mean(&t.lite[n - 20..]);
    assert!(late < 0.5 * settling, "lite: {settling:.2} then {late:.2}");
    assert!(late < 0.6, "lite ends {late:.2} st off");
    // Today's merge (the lite register without decay) lags, and the drill is far off. (These
    // simulated utterances each sample the whole register, so averaging their percentiles is
    // unbiased here; real phrases cover a few tones each, which makes the lite register narrow.)
    let merged = mean(&t.merged[n - 20..]);
    assert!(merged > 1.5 * late, "merged {merged:.2} vs lite {late:.2}");
    assert!(mean(&t.drill[n - 20..]) > 2.5);
}

#[test]
fn without_decay_the_lite_register_is_todays_merge_from_a_cold_start() {
    // Ruling R120: with no decay and no cap the lite register is `register_update`'s chain, bit
    // for bit: the first utterance's cold-start register, then `merge_register` for each.
    let mut rng = Rng::new(12);
    let mut lite: Option<Register> = None;
    let mut merged: Option<Register> = None;
    for k in 0..40 {
        let frames = utterance(&mut rng, 30 + k, 18.0 + (k % 3) as f64, 2.0);
        let syllables = 1 + (k % 4) as u32;
        lite = Some(roll_register_lite(
            lite.as_ref(),
            &frames,
            syllables,
            &RollingParams::POOLED,
        ));
        merged = Some(match &merged {
            None => cold_register(&frames, syllables),
            Some(r) => merge_register(r, &frames, syllables),
        });
        assert_eq!(lite, merged, "utterance {k}");
    }
}

#[test]
fn the_lite_register_forgets_with_the_same_half_life() {
    // A warm register (so many syllables behind it that the running mean has no say) hears
    // utterances of one pitch, 1 s of voice each (under the 1.32 s cap): after 30 s, one
    // half-life, its median is half as far from that pitch as it was.
    let warm = Register {
        floor_st: 10.0,
        median_st: 14.0,
        ceil_st: 18.0,
        n_syllables: 1_000_000,
    };
    let frames = vec![20.0f32; 100];
    let mut r = warm.clone();
    for _ in 0..30 {
        r = roll_register_lite(Some(&r), &frames, 3, &RollingParams::DEFAULT);
    }
    let left = f64::from(20.0 - r.median_st) / f64::from(20.0 - warm.median_st);
    assert!(
        (left - 0.5).abs() < 1e-5,
        "{left} of the distance left: {r:?}"
    );
}

#[test]
fn one_odd_utterance_moves_a_warm_lite_register_at_most_max_share_of_its_distance() {
    let params = RollingParams::DEFAULT;
    let share = f64::from(params.max_share.unwrap());
    let mut rng = Rng::new(5);
    // 300 phrases: 900 syllables, so the running mean's say (3/903) is under the cap's 3%.
    let b = settled_lite(&mut rng, 300, &params);
    // A 5 s shout an octave up, and one two octaves up.
    let shout = utterance(&mut rng, 500, SETTLED.0 + 12.0, 1.0);
    let high = utterance(&mut rng, 500, SETTLED.0 + 24.0, 1.0);
    let moves = |frames: &[f32]| {
        let a = roll_register_lite(Some(&b), frames, 3, &params);
        [
            a.floor_st - b.floor_st,
            a.median_st - b.median_st,
            a.ceil_st - b.ceil_st,
        ]
    };
    // Each number moves at most 3% of the way to the shout's own percentile (+ f32 rounding).
    let pct = |v: &[f32], p: usize| {
        let mut v = v.to_vec();
        v.sort_by(f32::total_cmp);
        f64::from(v[p * (v.len() - 1) / 100])
    };
    let levels = [b.floor_st, b.median_st, b.ceil_st];
    for (m, (level, p)) in moves(&shout).iter().zip(levels.iter().zip([5, 50, 95])) {
        let distance = pct(&shout, p) - f64::from(*level);
        assert!(
            f64::from(*m) <= share * distance + 0.02,
            "{m} of {distance}"
        );
        assert!(*m > 0.0);
    }
    // The weaker bound: unlike a pool's percentiles, all three numbers move, and the farther off
    // the utterance, the farther they move (the full register's median moved 0.1 st, here 0.36).
    let (near, far) = (moves(&shout), moves(&high));
    assert!(near[1] > 0.3, "{near:?}");
    for (n, f) in near.iter().zip(far) {
        assert!(f > 1.8 * n, "near {near:?} far {far:?}");
    }
}

#[test]
fn a_long_utterance_counts_as_the_cap_in_the_lite_register() {
    // A 20 s monologue one octave up moves the warm median exactly the cap's 3% of the way.
    let warm = Register {
        floor_st: 10.0,
        median_st: 14.0,
        ceil_st: 18.0,
        n_syllables: 1_000_000,
    };
    let frames = vec![26.0f32; 2000];
    let r = roll_register_lite(Some(&warm), &frames, 3, &RollingParams::DEFAULT);
    assert!(
        (f64::from(r.median_st) - (14.0 + 0.03 * 12.0)).abs() < 1e-5,
        "{r:?}"
    );
    // Without a cap the decay alone sets the say: 1 − 2^(−20/30) ≈ 0.37, then at most a half.
    let uncapped = RollingParams {
        half_life_s: Some(30.0),
        max_share: None,
    };
    let r = roll_register_lite(Some(&warm), &frames, 3, &uncapped);
    let w = 1.0 - (-20.0f64 / 30.0).exp2();
    assert!(
        (f64::from(r.median_st) - (14.0 + w * 12.0)).abs() < 1e-4,
        "{r:?}"
    );
}

#[test]
fn the_lite_register_learns_nothing_from_nothing_and_starts_cold() {
    let mut rng = Rng::new(4);
    let before = settled_lite(&mut rng, 10, &RollingParams::DEFAULT);
    let frames = utterance(&mut rng, 80, 30.0, 1.0);
    let params = RollingParams::DEFAULT;
    assert_eq!(
        roll_register_lite(Some(&before), &frames, 0, &params),
        before
    );
    let nothing = roll_register_lite(None, &frames, 0, &params);
    assert_eq!(nothing.n_syllables, 0);
    // From nothing learnt (no register, or one counting no syllables): the cold start.
    let cold = cold_register(&frames, 3);
    assert_eq!(roll_register_lite(None, &frames, 3, &params), cold);
    assert_eq!(
        roll_register_lite(Some(&nothing), &frames, 3, &params),
        cold
    );
    // Measured syllables without pitch only count.
    let after = roll_register_lite(Some(&before), &[f32::NAN], 2, &params);
    assert_eq!(after.n_syllables, before.n_syllables + 2);
    assert_eq!(after.median_st, before.median_st);
}

#[test]
fn the_lite_register_is_deterministic() {
    let x = settled_lite(&mut Rng::new(3), 50, &RollingParams::DEFAULT);
    let y = settled_lite(&mut Rng::new(3), 50, &RollingParams::DEFAULT);
    let bits = |r: &Register| [r.floor_st, r.median_st, r.ceil_st].map(f32::to_bits);
    assert_eq!(bits(&x), bits(&y));
    assert_eq!(x, y);
}
