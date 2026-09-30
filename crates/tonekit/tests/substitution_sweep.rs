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

use tonekit::{
    analyze, assess, AccentId, AnalyzeOptions, AssessRequest, Candidate, CandidateId,
    GradingTarget, LanguagePack, ToneId, ToneTarget,
};
use tonekit_testkit::{register_for, synth, SynthSpec, SynthSyllable};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

const RATE: u32 = 16_000;
const FULL_TONES: [&str; 4] = ["1", "2", "3", "4"];

/// Each full tone in each position, and no 3-3 pair (third-tone sandhi is not what this tests).
const READINGS: [[&str; 3]; 6] = [
    ["1", "2", "3"],
    ["2", "3", "4"],
    ["3", "4", "1"],
    ["4", "1", "2"],
    ["4", "1", "3"],
    ["2", "4", "1"],
];

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

fn knots(tone: &str, last: bool) -> Vec<f32> {
    match tone {
        "1" => vec![5.0, 5.0],
        "2" => vec![3.0, 5.0],
        "3" if last => vec![2.0, 1.0, 4.0],
        "3" => vec![2.0, 1.0],
        "4" => vec![5.0, 1.0],
        other => panic!("no spoken form for tone {other}"),
    }
}

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

/// `p_correct` of each syllable of `intended` on the analysed clip, graded alone (no distractors).
fn grade(a: &tonekit::Analysis, pack: &LanguagePack, intended: &[&str]) -> Vec<f32> {
    let request = AssessRequest {
        grading: GradingTarget {
            accent: AccentId("cmn-standard".into()),
            style: None,
            style_weight: 0.0,
        },
        intended: Candidate {
            id: CandidateId("spell".into()),
            targets: intended
                .iter()
                .map(|t| ToneTarget {
                    tone: ToneId((*t).into()),
                    lexical_variants: Vec::new(),
                    label: None,
                })
                .collect(),
        },
        distractors: Vec::new(),
        external: Vec::new(),
        compare_accents: Vec::new(),
    };
    assess(a, pack, &request)
        .unwrap()
        .syllables
        .iter()
        .map(|s| s.p_correct)
        .collect()
}

/// One single substitution: the spoken reading, the reading graded, which syllable differs, and
/// that syllable's `p_correct` under the wrong reading and under the spoken one.
struct Substitution {
    spoken: String,
    intended: String,
    position: usize,
    p_wrong: f32,
    p_correct: f32,
}

impl Substitution {
    fn graded_too_well(&self) -> bool {
        self.p_wrong >= 0.5 || self.p_wrong >= self.p_correct
    }

    fn describe(&self) -> String {
        format!(
            "spoken {} graded as {}: syllable {} p {:.3} (spoken tone {:.3})",
            self.spoken, self.intended, self.position, self.p_wrong, self.p_correct
        )
    }
}

/// Every single full-tone substitution of every reading, spoken under `c` by `speaker`.
fn sweep(c: Condition, speaker: (f32, f32)) -> Vec<Substitution> {
    let pack = LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap();
    let register = register_for(speaker.0, speaker.1);
    let mut out = Vec::new();
    for spoken in READINGS {
        let a = analyze(
            &clip(&spoken, c, speaker),
            RATE,
            Some(&register),
            &AnalyzeOptions::default(),
        )
        .unwrap();
        let right = grade(&a, &pack, &spoken);
        for position in 0..spoken.len() {
            for wrong in FULL_TONES.iter().filter(|&&t| t != spoken[position]) {
                let mut intended = spoken;
                intended[position] = wrong;
                out.push(Substitution {
                    spoken: spoken.join("-"),
                    intended: intended.join("-"),
                    position,
                    p_wrong: grade(&a, &pack, &intended)[position],
                    p_correct: right[position],
                });
            }
        }
    }
    out
}

/// Prints how many of `subs` graded too well, which, and the best-graded wrong tone; returns the
/// count.
fn report(label: &str, subs: &[Substitution]) -> usize {
    let misses: Vec<&Substitution> = subs.iter().filter(|s| s.graded_too_well()).collect();
    eprintln!(
        "{label}: {} of {} substitutions graded too well",
        misses.len(),
        subs.len()
    );
    for m in &misses {
        eprintln!("  {}", m.describe());
    }
    if let Some(worst) = subs.iter().max_by(|a, b| a.p_wrong.total_cmp(&b.p_wrong)) {
        eprintln!("  highest wrong: {}", worst.describe());
    }
    misses.len()
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
