//! f0 and energy tracks for tonekit (spec §6.1).
//!
//! Every later stage reads the same two frame-level tracks: an [`F0Track`](tonekit_core::F0Track)
//! and an [`EnergyTrack`](tonekit_core::EnergyTrack). Both have exactly `pcm.len() / HOP + 1`
//! frames; frame `i` is centred on sample `i * HOP` (10 ms per frame at 16 kHz).
//!
//! * [`F0Provider`] is the extension point; [`Pyin`] is the built-in provider. An external track
//!   is brought to the right length with [`fit_length`].
//! * [`repair_octaves`] post-processes a track, fixing isolated octave jumps.
//! * [`clipping_ratio`] and [`snr_db`] are the signal checks behind the `Clipped` and `LowSnr`
//!   issues.

#![forbid(unsafe_code)]

mod checks;
mod energy;
mod provider;
mod pyin_provider;
mod repair;

pub use checks::{clipping_ratio, snr_db};
pub use energy::energy;
pub use provider::{fit_length, F0Provider};
pub use pyin_provider::Pyin;
pub use repair::repair_octaves;
