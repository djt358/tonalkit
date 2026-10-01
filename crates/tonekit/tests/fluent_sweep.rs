//! Fluent speech (S0.5 R1): native speakers run syllables together, so the substitution sweep is
//! repeated with no pause between syllables.
//!
//! The same six readings as `substitution_sweep.rs` (every full tone in every position, tones
//! spoken as ruling R8 fixes them), rendered by `tonekit_testkit::synth_fluent`: contiguous
//! syllables whose pitch glides from one tone into the next (a raised cosine centred on the join)
//! and whose level dips at the join without falling silent, at 5 or 6 syllables per second, by
//! four speakers ([`FLUENT_SPEAKERS`]: male-low 85–160 Hz, octave-spanning 100–200 Hz, female
//! 180–330 Hz, wide 110–260 Hz) on their warm registers, in three conditions. Each clip must
//! segment into exactly three nuclei, and for every single full-tone substitution of the spoken
//! reading the substituted syllable must grade below 0.5 and below the same syllable of the
//! spoken reading.

mod sweep;

use sweep::{cmn, knots, report, substitutions, Substitution, RATE, READINGS};
use tonekit::{analyze, AnalyzeOptions, LanguagePack};
use tonekit_testkit::{synth_fluent, FluentSpec, FluentSyllable, Speaker, FLUENT_SPEAKERS};

/// Width of the energy dip at each join: about a sonorant consonant's length.
const DIP_MS: f32 = 80.0;

/// How fast and how smoothly the reading is spoken.
#[derive(Clone, Copy, Debug)]
struct Condition {
    name: &'static str,
    syllables_per_s: f32,
    glide_ms: f32,
    dip_db: f32,
    /// Unvoiced onset of the middle syllable (a fricative such as "s" or "x"); 0 for none.
    middle_onset_ms: f32,
    snr_db: Option<f32>,
}

/// The CI conditions.
const CONDITIONS: [Condition; 3] = [
    Condition {
        name: "5 syl/s, 0 dB dip, 40 ms glide",
        syllables_per_s: 5.0,
        glide_ms: 40.0,
        dip_db: 0.0,
        middle_onset_ms: 0.0,
        snr_db: None,
    },
    Condition {
        name: "5 syl/s, 6 dB dip, 60 ms glide",
        syllables_per_s: 5.0,
        glide_ms: 60.0,
        dip_db: 6.0,
        middle_onset_ms: 0.0,
        snr_db: None,
    },
    Condition {
        name: "6 syl/s, 3 dB dip, 30 ms glide, 25 dB SNR",
        syllables_per_s: 6.0,
        glide_ms: 30.0,
        dip_db: 3.0,
        middle_onset_ms: 0.0,
        snr_db: Some(25.0),
    },
];

fn clip(reading: &[&str], c: &Condition, speaker: &Speaker) -> Vec<f32> {
    let last = reading.len() - 1;
    synth_fluent(&FluentSpec {
        floor_hz: speaker.floor_hz,
        ceil_hz: speaker.ceil_hz,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: reading
            .iter()
            .enumerate()
            .map(|(i, tone)| FluentSyllable {
                unvoiced_onset_ms: if i == 1 { c.middle_onset_ms } else { 0.0 },
                ..FluentSyllable::at_rate(knots(tone, i == last), c.syllables_per_s)
            })
            .collect(),
        glide_ms: c.glide_ms,
        dip_db: c.dip_db,
        dip_ms: DIP_MS,
        snr_db: c.snr_db,
        seed: 1,
    })
    .pcm
}

/// One condition and speaker: the readings that did not segment into three nuclei, and every
/// single substitution of the readings that did.
struct Outcome {
    missegmented: Vec<String>,
    substitutions: Vec<Substitution>,
}

fn sweep(pack: &LanguagePack, c: &Condition, speaker: &Speaker) -> Outcome {
    let register = speaker.register();
    let mut out = Outcome {
        missegmented: Vec::new(),
        substitutions: Vec::new(),
    };
    for spoken in READINGS {
        let a = analyze(
            &clip(&spoken, c, speaker),
            RATE,
            Some(&register),
            &AnalyzeOptions::default(),
        )
        .unwrap();
        let frames: Vec<u32> = a.nuclei.iter().map(|n| n.frame).collect();
        if frames.len() != spoken.len() {
            out.missegmented
                .push(format!("{}: nuclei at {frames:?}", spoken.join("-")));
        }
        out.substitutions.extend(substitutions(&a, pack, spoken));
    }
    out
}

/// Runs `conditions` × [`FLUENT_SPEAKERS`], printing each cell; returns the cells that failed with
/// their missegmented-clip and too-well-graded counts.
fn run(conditions: &[Condition]) -> Vec<(String, usize, usize)> {
    let pack = cmn();
    let mut failed = Vec::new();
    for c in conditions {
        for speaker in &FLUENT_SPEAKERS {
            let label = format!("{}, {}", c.name, speaker.name);
            let outcome = sweep(&pack, c, speaker);
            for m in &outcome.missegmented {
                eprintln!("{label}: missegmented {m}");
            }
            let misses = report(&label, &outcome.substitutions);
            if misses > 0 || !outcome.missegmented.is_empty() {
                failed.push((label, outcome.missegmented.len(), misses));
            }
        }
    }
    failed
}

#[test]
fn fluent_speech_segments_and_no_substitution_grades_as_well_as_the_spoken_tone() {
    let failed = run(&CONDITIONS);
    assert!(
        failed.is_empty(),
        "(cell, missegmented clips of 6, substitutions graded too well of 54): {failed:?}"
    );
}

/// Report only: the wider matrix (4 to 6 syllables per second, dips of 0 to 12 dB, 30 or 60 ms
/// glides, a fricative onset on the middle syllable, noise). Run with `--ignored --nocapture`.
#[test]
#[ignore = "report only: the full fluent-speech matrix is measured, not asserted"]
fn fluent_speech_full_matrix_report() {
    let mut matrix = Vec::new();
    for syllables_per_s in [4.0, 5.0, 6.0] {
        for dip_db in [0.0, 3.0, 6.0, 12.0] {
            for glide_ms in [30.0, 60.0] {
                for (middle_onset_ms, snr_db) in [(0.0, None), (30.0, None), (0.0, Some(20.0))] {
                    matrix.push(Condition {
                        name: "",
                        syllables_per_s,
                        glide_ms,
                        dip_db,
                        middle_onset_ms,
                        snr_db,
                    });
                }
            }
        }
    }
    let names: Vec<String> = matrix
        .iter()
        .map(|c| {
            format!(
                "{} syl/s, {} dB dip, {} ms glide, {} ms onset, SNR {:?}",
                c.syllables_per_s, c.dip_db, c.glide_ms, c.middle_onset_ms, c.snr_db
            )
        })
        .collect();
    let named: Vec<Condition> = matrix
        .iter()
        .zip(&names)
        .map(|(c, n)| Condition {
            name: Box::leak(n.clone().into_boxed_str()),
            ..*c
        })
        .collect();
    let failed = run(&named);
    eprintln!("{} of {} cells failed", failed.len(), named.len() * 4);
    for f in &failed {
        eprintln!("  {f:?}");
    }
}
