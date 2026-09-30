//! Speaker register, Chao-scale normalisation, tone-shape extraction and style fitting (spec §5, §6.3).

#![forbid(unsafe_code)]

mod chao;
mod extract;
mod fit;
mod register;
mod style;

pub use chao::{hz_to_st, st_to_chao, voiced_semitones};
pub use extract::{extract, extract_nucleus, Extracted};
pub use register::{cold_register, is_cold, merge_register};
pub use style::fit_style;
