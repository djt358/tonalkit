//! Ruling R50: a wrong tone never grades as well as the tone that was spoken.
//!
//! Before R50 the closed-set decoder extracted each candidate's shape on the boundary pair its
//! path chose, so a wrong target could pick a span reaching into the pYIN bleed frames beside a
//! syllable and bend the contour its way ("span shopping"): intended 4-2-3 on spoken 4-1-3 graded
//! the wrong middle syllable above the right one. Every nucleus now has one shape that every
//! candidate is scored on.
//!
//! The sweep: six three-syllable readings that put each full tone in each position, spoken by a
//! 110–190 Hz speaker (not an octave, so no pitch lands on a Chao knot by accident) in four
//! conditions. For every single full-tone substitution of the spoken reading, the substituted
//! syllable must grade below 0.5 and below the same syllable of the spoken reading. Tones are
//! realised as ruling R8 fixes them: "1" → [5,5], "2" → [3,5], "3" → [2,1,4] when phrase-final and
//! [2,1] otherwise, "4" → [5,1]; 250 ms syllables, 200 ms lead and tail, the speaker's warm register.
//! Syllables run together are `fluent_sweep.rs`'s job.

mod sweep;

use sweep::{cmn, knots, report, substitutions, Substitution, RATE, READINGS};
use tonekit::{analyze, AnalyzeOptions};
use tonekit_testkit::{register_for, synth, SynthSpec, SynthSyllable};

/// How the clips are spoken: silence after each syllable, unvoiced onset (a consonant) at the start
/// of each, and white noise at an SNR.
#[derive(Clone, Copy, Debug)]
struct Condition {
    name: &'static str,
    gap_ms: f32,
    onset_ms: f32,
    snr_db: Option<f32>,
}

const CONDITIONS: [Condition; 4] = [
    Condition {
        name: "60 ms gap",
        gap_ms: 60.0,
        onset_ms: 0.0,
        snr_db: None,
    },
    Condition {
        name: "150 ms gap",
        gap_ms: 150.0,
        onset_ms: 0.0,
        snr_db: None,
    },
    Condition {
        name: "60 ms gap, 25 dB SNR",
        gap_ms: 60.0,
        onset_ms: 0.0,
        snr_db: Some(25.0),
    },
    Condition {
        name: "30 ms gap + 40 ms onset, 25 dB SNR",
        gap_ms: 30.0,
        onset_ms: 40.0,
        snr_db: Some(25.0),
    },
];

fn clip(reading: &[&str], c: Condition, (floor_hz, ceil_hz): (f32, f32)) -> Vec<f32> {
    let last = reading.len() - 1;
    synth(&SynthSpec {
        floor_hz,
        ceil_hz,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: reading
            .iter()
            .enumerate()
            .map(|(i, tone)| SynthSyllable {
                chao: knots(tone, i == last),
                dur_ms: 250.0,
                gap_after_ms: if i == last { 0.0 } else { c.gap_ms },
                unvoiced_onset_ms: c.onset_ms,
                creak: None,
            })
            .collect(),
        snr_db: c.snr_db,
        seed: 1,
    })
    .pcm
}

/// Every single full-tone substitution of every reading, spoken under `c` by `speaker`.
fn sweep(c: Condition, speaker: (f32, f32)) -> Vec<Substitution> {
    let pack = cmn();
    let register = register_for(speaker.0, speaker.1);
    READINGS
        .iter()
        .flat_map(|&spoken| {
            let a = analyze(
                &clip(&spoken, c, speaker),
                RATE,
                Some(&register),
                &AnalyzeOptions::default(),
            )
            .unwrap();
            substitutions(&a, &pack, &spoken)
        })
        .collect()
}

#[test]
fn no_single_substitution_grades_as_well_as_the_spoken_tone() {
    let failed: Vec<(&str, usize)> = CONDITIONS
        .iter()
        .map(|c| (c.name, report(c.name, &sweep(*c, (110.0, 190.0)))))
        .filter(|&(_, misses)| misses > 0)
        .collect();
    assert!(
        failed.is_empty(),
        "substitutions graded too well: {failed:?}"
    );
}

/// Report only (final review M9): syllables with no pause between them, where pYIN's window
/// straddles two tones, for this sweep's speaker and for a 100–200 Hz one (whose contiguous
/// T4 → T1 pulls pYIN onto the subharmonic). Run with `--ignored --nocapture`.
#[test]
#[ignore = "report only: contiguous syllables are measured, not asserted (M9)"]
fn contiguous_syllables_report() {
    let contiguous = Condition {
        name: "contiguous",
        gap_ms: 0.0,
        onset_ms: 0.0,
        snr_db: None,
    };
    for speaker in [(110.0, 190.0), (100.0, 200.0)] {
        let label = format!("contiguous, {}-{} Hz", speaker.0, speaker.1);
        report(&label, &sweep(contiguous, speaker));
    }
}
