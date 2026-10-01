//! Deterministic synthetic "speech" with exact f0 ground truth. Dev-only: no later crate ships it.
//!
//! Two generators render a row of syllables, each a Chao contour plus timing, to 16 kHz PCM
//! together with the frame-level f0 the signal was built from, so f0 tracking, segmentation,
//! shape extraction and decoding can all be tested without audio files:
//!
//! - [`synth`] renders a [`SynthSpec`]: syllables with silence between them (the P0 generator);
//! - [`synth_fluent`] renders a [`FluentSpec`]: syllables run together, with f0 glides and energy
//!   dips at the joins, as native speakers say them. [`FLUENT_SPEAKERS`] are its sweep's voices.
//!
//! # Signal model of [`synth`]
//!
//! Timeline: `lead_ms` of silence; then per syllable `unvoiced_onset_ms` of noise, the voiced part
//! (`dur_ms - unvoiced_onset_ms`) and `gap_after_ms` of silence; then `tail_ms` of silence. Each
//! boundary is rounded to the nearest sample. An onset equal to (or longer than) `dur_ms` makes the
//! syllable fully whispered: noise only, no f0.
//!
//! - **Voiced part:** the sum over harmonics `h` with `h·f0 < 4000 Hz` of `sin(h·φ)/h`, where φ
//!   is accumulated per sample from the instantaneous f0. f0 comes from the syllable's Chao knots,
//!   evenly spaced over the voiced part (`u = i/(n−1)`), linearly interpolated in Chao and mapped
//!   to Hz per sample by [`chao_to_hz`]. A raised-cosine envelope ramps the amplitude over 20 ms at
//!   each edge (shrunk to half the part when it is shorter than 40 ms).
//! - **Creak:** `creak: Some((a, b))` replaces the fraction range `[a, b)` of the voiced part with
//!   noise and no f0. The pitch of the rest of the syllable does not move.
//! - **Noise levels:** Gaussian, with standard deviation 0.1 (unvoiced onset) or 0.05 (creak) times
//!   the voiced peak, meaning the largest |x| of the harmonic signal before normalisation (1.0 if
//!   there is none).
//! - **SNR:** `snr_db: Some(s)` adds white Gaussian noise over the whole buffer with RMS equal to
//!   the RMS of the voiced samples divided by `10^(s/20)`. Nothing is added when no sample is voiced.
//! - **Level:** finally the whole buffer is scaled so its peak |x| is 0.5.
//!
//! # Signal model of [`synth_fluent`]
//!
//! Timeline: `lead_ms` of silence; then the syllables back to back, each `dur_ms` long (its
//! unvoiced onset included; [`FluentSyllable::at_rate`] sets it from a speaking rate); then
//! `tail_ms` of silence. A *voiced join* is one where the next syllable has no unvoiced onset: the
//! voicing runs straight on, so the voiced syllables between consonants form one voiced stretch.
//!
//! - **f0:** each syllable's Chao knots are spread over its own voiced part as in [`synth`]
//!   (interpolated in semitones). At each voiced join, the `glide_ms` centred on it (at most half
//!   of either neighbour's voiced part on its side) is replaced by a raised-cosine transition, in
//!   semitones, from the left syllable's contour at the glide's start to the right one's at its
//!   end. Glides are the only coarticulation of pitch.
//! - **Amplitude:** the harmonic source of [`synth`] with one phase per voiced stretch (no phase
//!   jump at a join), a 20 ms raised-cosine ramp at each stretch edge (shrunk to half the stretch
//!   when shorter), and at each voiced join a dip of `dip_db` over `dip_ms` centred on it: the gain
//!   in dB is `−dip_db·½(1 + cos(π·t/(dip_ms/2)))` for `|t| < dip_ms/2`, so the level is lowest
//!   exactly at the join and never silent. Dips that overlap multiply. A join into a syllable with
//!   an unvoiced onset has no glide and no dip; the voicing ramps out before it and back in after
//!   the onset.
//! - **Onset noise, SNR and level** are as in [`synth`] (no creak).
//!
//! # Ground truth
//!
//! `f0_truth[i]` describes sample `i·160` (clamped to the last sample) and is `Some(hz)` exactly
//! when that sample is in a harmonic region (glides included); there are `pcm.len()/160 + 1`
//! entries. `syllable_frames[k]` is `(round(start_ms/10), round(end_ms/10))` for syllable `k`,
//! spanning its onset and voiced part but not its gap (half-open, halves round away from zero).
//! In fluent speech consecutive syllables share their edge frame.
//!
//! # Determinism
//!
//! One seeded xorshift64 stream is drawn in timeline order (onset noise, creak
//! noise, then SNR noise), so a spec that needs no noise is independent of `seed`, and adding
//! `snr_db` does not change the onset or creak noise. The output is bit-identical for the same
//! spec on the same platform (it uses the platform's `f64` `sin`/`cos`/`ln`).

#![forbid(unsafe_code)]

mod fluent;
mod pitch;
mod render;
mod rng;
mod spaced;
mod speakers;

pub use fluent::{synth_fluent, FluentSpec, FluentSyllable};
pub use pitch::{chao_to_hz, register_for};
pub use spaced::{synth, SynthSpec, SynthSyllable};
pub use speakers::{Speaker, FEMALE, FLUENT_SPEAKERS, MALE_LOW, OCTAVE_SPANNING, WIDE};

/// A rendered clip and the truth it was built from.
#[derive(Clone, Debug, PartialEq)]
pub struct Synth {
    /// 16 kHz mono samples, peak |x| = 0.5 (all zeros if nothing was generated).
    pub pcm: Vec<f32>,
    /// `pcm.len()/160 + 1` entries; entry `i` is the f0 at sample `i·160`, `None` if unvoiced.
    pub f0_truth: Vec<Option<f32>>,
    /// Per syllable, half-open `(start_frame, end_frame)`: onset and voiced part, not the gap.
    pub syllable_frames: Vec<(u32, u32)>,
}
