//! Speaker register, Chao-scale normalisation, tone-shape extraction and style fitting (spec §5, §6.3).

#![forbid(unsafe_code)]

mod chao;
mod extract;
mod fit;
mod joins;
mod pool;
mod register;
mod rolling;
mod rolling_lite;
mod style;

pub use chao::{hz_to_st, speech_semitones, st_to_chao, voiced_semitones};
pub use extract::{extract, extract_nucleus, Extracted};
pub use joins::{Joins, JOIN_TRIM_FRAMES};
pub use register::{cold_register, is_cold, merge_register};
pub use rolling::{roll_register, utterance_cap_s};
pub use rolling_lite::roll_register_lite;
pub use style::fit_style;
