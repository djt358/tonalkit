//! f0 and energy tracks for tonekit (spec §6.1).
//!
//! Every later stage reads the same two frame-level tracks: an [`F0Track`](tonekit_core::F0Track)
//! and an [`EnergyTrack`](tonekit_core::EnergyTrack). Both have exactly `pcm.len() / HOP + 1`
//! frames (10 ms per frame at 16 kHz); frame `i` describes the signal around sample `i * HOP`.
//! The energy window is exactly centred there. [`Pyin`] matches it to within about +-0.3 frame
//! over 80 to 300 Hz, after compensating the half-frame lag that the `pyin` crate has (see its docs).
//!
//! * [`F0Provider`] is the extension point; [`Pyin`] is the built-in provider. An external track
//!   is brought to the right length with [`fit_length`].
//! * [`unpitch_creak`] removes pYIN's pitch from creak and noise it tracks near its floor, and
//!   [`recover_pitch`] gives pYIN's track a pitch where it left loud, vowel-like, clearly periodic
//!   speech unvoiced (ruling R105).
//! * [`repair_subharmonics`] and then [`repair_octaves`] post-process a track: the first doubles
//!   frames whose signal repeats at half the tracked period (a whole run on the subharmonic), the
//!   second fixes isolated octave jumps within each voiced run.
//! * [`clipping_ratio`] and [`snr_db`] are the signal checks behind the `Clipped` and `LowSnr`
//!   issues.

#![forbid(unsafe_code)]

mod checks;
mod creak;
mod energy;
mod nsdf;
mod provider;
mod pyin_provider;
mod recover;
mod repair;
mod sonority;
mod subharmonic;

pub use checks::{clipping_ratio, snr_db};
pub use creak::unpitch_creak;
pub use energy::energy;
pub use provider::{fit_length, F0Provider};
pub use pyin_provider::Pyin;
pub use recover::recover_pitch;
pub use repair::repair_octaves;
pub use sonority::sonority;
pub use subharmonic::repair_subharmonics;
