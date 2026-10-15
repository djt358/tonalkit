//! The lite rolling register (ruling R120): a rolling register's half-life and per-utterance cap
//! on the four numbers of a [`Register`], for an app that would rather not store a pitch
//! histogram ([`crate::roll_register`] keeps 540 bins).
//!
//! Each utterance moves floor, median and ceiling `w` of the way to its own p5, p50 and p95, as
//! [`crate::merge_register`] does, but `w` never falls below the share of a full pool that the
//! utterance's counted speech would take: `w = min(0.5, max(u/(n+u), 1 − 2^(−counted/H)))`, with
//! `counted` its voiced seconds capped at `−H·log2(1 − max_share)` as in the full register. So:
//!
//! - **Same half-life.** Once the decay term is the larger, an older utterance's say shrinks by
//!   `2^(−c/H)` for every `c` seconds counted after it: it weighs half after `H` seconds of newer
//!   speech.
//! - **Same cap.** `1 − 2^(−counted/H)` is at most `max_share`, so once `u/(n+u)` is below it too
//!   (for an utterance of `u` syllables, once the register counts about `u/max_share`: some 100
//!   syllables for a three-syllable phrase at the default 3%) no utterance moves a number more than
//!   `max_share` of the way to its own percentile.
//! - **Before that** it is today's `register_update` merge (`u/(n+u)`, at most one half), which
//!   weighs every syllable alike; with no decay and no cap it is exactly that merge, utterance
//!   after utterance from a cold start. For short phrases the decay takes over after a few hundred
//!   syllables at the default, about when the full register's pool fills.
//!
//! How it differs from the full register's weighted percentiles:
//!
//! - It averages each utterance's own percentiles instead of taking percentiles of every frame.
//!   Pooled percentiles include the spread between utterances (a phrase of high tones, then one of
//!   low tones); an average of each utterance's p5 and p95 does not, so the lite register is
//!   narrower, the more so the shorter the utterances (a one-syllable utterance's p5 and p95 are
//!   both its own tone's level).
//! - Its outlier bound is weaker. One utterance moves each of the three numbers by at most
//!   `w · d`, where `d` is how far that utterance's percentile is from it: the move grows with how
//!   far off the utterance is, and floor, median and ceiling all move. A pool's p95 can rise at
//!   most to its `0.95/(1 − share)` quantile, however far off the utterance, and its median and
//!   floor barely move.
//! - While cold, one utterance can move it half the way (the merge's cap), where the pool counts
//!   it as at most `−H·log2(1 − max_share)` seconds from the start.

use tonekit_core::{Register, RollingParams};

use crate::register::{cold_register, fallback_register, merge_at_least};
use crate::rolling::{counted_seconds, decay, FRAME_S};

/// Rolls one utterance into a lite register (`previous`, `None` for nothing yet): `voiced_st` are
/// its speech-only voiced semitones (`Analysis::voiced_st`, ruling R106) and `syllables` how many
/// of its syllables were measured (ruling R38).
///
/// 1. With no syllable measured there is nothing to learn: `previous` comes back as it is (or
///    the fixed fallback register counting no syllables).
/// 2. With nothing learnt yet (`previous` is `None` or counts no syllables) the result is the
///    utterance's cold-start register ([`cold_register`]: p5 − 2 st, p50, p95 + 2 st).
/// 3. Otherwise floor, median and ceiling move `w = min(0.5, max(u/(n+u), 1 − 2^(−counted/H)))`
///    of the way to the utterance's p5, p50 and p95 (the module's documentation says why), at
///    least 4 st wide, and the count grows by `syllables`. Without voiced frames only the count
///    changes.
///
/// `params` are assumed usable ([`RollingParams::problem`] is `None`) and `previous` a register
/// that can be graded against. With [`RollingParams::POOLED`] it is the chain of `register_update`
/// merges from a cold start.
pub fn roll_register_lite(
    previous: Option<&Register>,
    voiced_st: &[f32],
    syllables: u32,
    params: &RollingParams,
) -> Register {
    if syllables == 0 {
        return previous.cloned().unwrap_or_else(fallback_register);
    }
    let Some(previous) = previous.filter(|r| r.n_syllables > 0) else {
        return cold_register(voiced_st, syllables);
    };
    let frames = voiced_st.iter().filter(|st| st.is_finite()).count();
    let counted = counted_seconds(frames as f64 * FRAME_S, params);
    merge_at_least(previous, voiced_st, syllables, 1.0 - decay(counted, params))
}
