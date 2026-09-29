//! Plain-data types shared by every tonekit crate (spec §5). No logic lives here.

#![forbid(unsafe_code)]

// With the `ffi` feature the exported types derive UniFFI's traits (Swift bindings, Task 12).
// `crate::UniFfiTag` is what those derives are generic over, so the crate needs its own scaffolding.
#[cfg(feature = "ffi")]
uniffi::setup_scaffolding!();

mod analysis;
mod decode;
mod error;
mod evidence;
mod ids;
mod judgement;
mod lattice;
mod register;
mod shape;
mod signal;
mod style;
mod target;

pub use analysis::*;
pub use decode::*;
pub use error::*;
pub use evidence::*;
pub use ids::*;
pub use judgement::*;
pub use lattice::*;
pub use register::*;
pub use shape::*;
pub use signal::*;
pub use style::*;
pub use target::*;
