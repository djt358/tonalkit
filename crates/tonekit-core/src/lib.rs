//! Plain-data types shared by every tonekit crate (spec §5). No logic lives here.

#![forbid(unsafe_code)]

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
