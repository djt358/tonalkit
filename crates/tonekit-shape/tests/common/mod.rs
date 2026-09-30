//! Shared test scaffolding: synthesise one syllable and hand `extract` the ground-truth f0.
#![allow(dead_code)] // each test binary uses a different subset

use tonekit_core::{F0Frame, F0Track, Register, TbuSpan, ToneShape};
use tonekit_shape::{extract, Extracted};
use tonekit_testkit::{register_for, synth, SynthSpec, SynthSyllable};

pub struct Case {
    pub f0: F0Track,
    pub span: TbuSpan,
    pub register: Register,
}

/// A track built straight from f0 truth: `voiced_p` 1.0 where the truth has an f0, 0.0 elsewhere.
pub fn truth_track(f0_truth: &[Option<f32>]) -> F0Track {
    F0Track {
        frames: f0_truth
            .iter()
            .map(|hz| F0Frame {
                hz: *hz,
                voiced_p: if hz.is_some() { 1.0 } else { 0.0 },
            })
            .collect(),
        provider: "truth".to_string(),
    }
}

/// One syllable (lead/tail 200 ms, no onset, creak or noise) for a speaker with the given
/// floor and ceiling; the register is the exact one for that speaker.
pub fn case(chao: Vec<f32>, floor_hz: f32, ceil_hz: f32, dur_ms: f32) -> Case {
    let s = synth(&SynthSpec {
        floor_hz,
        ceil_hz,
        lead_ms: 200.0,
        tail_ms: 200.0,
        snr_db: None,
        seed: 1,
        syllables: vec![SynthSyllable {
            chao,
            dur_ms,
            gap_after_ms: 0.0,
            unvoiced_onset_ms: 0.0,
            creak: None,
        }],
    });
    let (start_frame, end_frame) = s.syllable_frames[0];
    Case {
        f0: truth_track(&s.f0_truth),
        span: TbuSpan {
            start_frame,
            end_frame,
        },
        register: register_for(floor_hz, ceil_hz),
    }
}

pub fn extract_case(c: &Case) -> Extracted {
    extract(&c.f0, &c.span, &c.register).expect("truth track is voiced")
}

pub fn shape_of(chao: Vec<f32>, floor_hz: f32, ceil_hz: f32, dur_ms: f32) -> ToneShape {
    extract_case(&case(chao, floor_hz, ceil_hz, dur_ms)).shape
}

/// `shape_of` at floor 100 Hz / ceiling 200 Hz, returning the issues too.
pub fn extract_of(chao: Vec<f32>, dur_ms: f32) -> Extracted {
    extract_case(&case(chao, 100.0, 200.0, dur_ms))
}
