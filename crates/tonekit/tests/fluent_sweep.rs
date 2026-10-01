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
        syllables_per_s: 5.0,
        glide_ms: 40.0,
        dip_db: 0.0,
        middle_onset_ms: 0.0,
        snr_db: None,
    },
    Condition {
        syllables_per_s: 5.0,
        glide_ms: 60.0,
        dip_db: 6.0,
        middle_onset_ms: 0.0,
        snr_db: None,
    },
    Condition {
        syllables_per_s: 6.0,
        glide_ms: 30.0,
        dip_db: 3.0,
        middle_onset_ms: 0.0,
        snr_db: Some(25.0),
    },
];

impl Condition {
    /// "5 syl/s, 6 dB dip, 60 ms glide", then the onset and the SNR when there are any.
    fn label(&self) -> String {
        let mut label = format!(
            "{} syl/s, {} dB dip, {} ms glide",
            self.syllables_per_s, self.dip_db, self.glide_ms
        );
        if self.middle_onset_ms > 0.0 {
            label += &format!(", {} ms onset", self.middle_onset_ms);
        }
        if let Some(snr) = self.snr_db {
            label += &format!(", {snr} dB SNR");
        }
        label
    }
}

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

/// A clip the CI sweep knows it cannot pass yet, and why (see the rulings in the R1 report).
struct Gap {
    condition: &'static str,
    /// `None`: every speaker.
    speaker: Option<&'static str>,
    reading: &'static str,
    kind: GapKind,
    why: &'static str,
}

#[derive(Clone, Copy, PartialEq)]
enum GapKind {
    /// No acoustic cue separates two syllables: nothing about the clip is asserted.
    Unsegmentable,
    /// Segmented right, and the spoken tone still grades above every substitution, but a wrong
    /// tone can reach 0.5.
    Ambiguous,
}

const A: &str = "5 syl/s, 0 dB dip, 40 ms glide";
const C: &str = "6 syl/s, 3 dB dip, 30 ms glide, 25 dB SNR";

/// The known gaps (ruling R62). The 0 dB condition has no level dip at all, so two syllables are
/// told apart only where pYIN loses the pitch between them (ruling R58); a 2-Chao glide (T1 → T2)
/// or no glide at all (T2 → T4 meeting at the ceiling) leaves it tracking straight through.
const GAPS: [Gap; 6] = [
    Gap {
        condition: A,
        speaker: None,
        reading: "1-2-3",
        kind: GapKind::Unsegmentable,
        why: "T1 → T2 is a 2-Chao glide at a flat level: no dip, no pitch break",
    },
    Gap {
        condition: A,
        speaker: None,
        reading: "4-1-2",
        kind: GapKind::Unsegmentable,
        why: "T1 → T2 is a 2-Chao glide at a flat level: no dip, no pitch break",
    },
    Gap {
        condition: A,
        speaker: None,
        reading: "2-4-1",
        kind: GapKind::Unsegmentable,
        why: "T2 → T4 meet at the ceiling at a flat level: no glide, no dip, no pitch break",
    },
    Gap {
        condition: A,
        speaker: Some("wide"),
        reading: "4-1-3",
        kind: GapKind::Unsegmentable,
        why: "pYIN loses the 14 st T4 → T1 jump for only 2 frames, which a voiced run bridges",
    },
    Gap {
        condition: C,
        speaker: Some("wide"),
        reading: "2-3-4",
        kind: GapKind::Ambiguous,
        why: "a 15 st T4 fall in ~150 ms (beyond the human maximum speed of pitch change): pYIN \
              loses its high start, and the mid fall it keeps fits T3 at 0.52",
    },
    Gap {
        condition: C,
        speaker: Some("wide"),
        reading: "3-4-1",
        kind: GapKind::Ambiguous,
        why: "a 15 st T4 fall in ~150 ms (beyond the human maximum speed of pitch change): pYIN \
              loses both its ends, and the mid fall it keeps fits T3 at 0.60",
    },
];

fn gap(condition: &str, speaker: &str, reading: &str) -> Option<&'static Gap> {
    GAPS.iter().find(|g| {
        g.condition == condition && g.speaker.is_none_or(|s| s == speaker) && g.reading == reading
    })
}

/// What one clip did: whether it segmented into one nucleus per syllable, and every single
/// substitution graded on it.
struct Clip {
    reading: String,
    nuclei: Vec<u32>,
    substitutions: Vec<Substitution>,
}

impl Clip {
    fn segmented(&self) -> bool {
        self.nuclei.len() == 3
    }

    fn graded_too_well(&self) -> usize {
        self.substitutions
            .iter()
            .filter(|s| s.graded_too_well())
            .count()
    }

    fn ranked_wrong(&self) -> usize {
        self.substitutions
            .iter()
            .filter(|s| s.ranked_wrong())
            .count()
    }
}

fn sweep(pack: &LanguagePack, c: &Condition, speaker: &Speaker) -> Vec<Clip> {
    let register = speaker.register();
    READINGS
        .iter()
        .map(|&spoken| {
            let a = analyze(
                &clip(&spoken, c, speaker),
                RATE,
                Some(&register),
                &AnalyzeOptions::default(),
            )
            .unwrap();
            Clip {
                reading: spoken.join("-"),
                nuclei: a.nuclei.iter().map(|n| n.frame).collect(),
                substitutions: substitutions(&a, pack, spoken),
            }
        })
        .collect()
}

/// Runs `conditions` × [`FLUENT_SPEAKERS`], printing each cell (clips that missegmented, then the
/// substitutions as `report` prints them); returns every clip with its condition and speaker.
fn run(conditions: &[Condition]) -> Vec<(String, &'static str, Clip)> {
    let pack = cmn();
    let mut out = Vec::new();
    for c in conditions {
        for speaker in &FLUENT_SPEAKERS {
            let label = format!("{}, {}", c.label(), speaker.name);
            let clips = sweep(&pack, c, speaker);
            let missegmented = clips.iter().filter(|k| !k.segmented()).count();
            eprintln!("{label}: {missegmented} of 6 clips missegmented");
            for k in clips.iter().filter(|k| !k.segmented()) {
                eprintln!("  {}: nuclei at {:?}", k.reading, k.nuclei);
            }
            report(&label, clips.iter().flat_map(|k| &k.substitutions));
            out.extend(clips.into_iter().map(|k| (c.label(), speaker.name, k)));
        }
    }
    out
}

#[test]
fn fluent_speech_segments_and_no_substitution_grades_as_well_as_the_spoken_tone() {
    let mut failed = Vec::new();
    for (condition, speaker, clip) in run(&CONDITIONS) {
        let at = format!("{condition}, {speaker}, {}", clip.reading);
        let (segmented, too_well, ranked_wrong) = (
            clip.segmented(),
            clip.graded_too_well(),
            clip.ranked_wrong(),
        );
        match gap(&condition, speaker, &clip.reading) {
            None if !segmented || too_well > 0 => failed.push(format!(
                "{at}: nuclei {:?}, {too_well} of 9 graded too well",
                clip.nuclei
            )),
            Some(g) if g.kind == GapKind::Ambiguous && (!segmented || ranked_wrong > 0) => failed
                .push(format!(
                    "{at} (known gap: {}): nuclei {:?}, {ranked_wrong} of 9 ranked above the \
                     spoken tone",
                    g.why, clip.nuclei
                )),
            Some(g) if segmented && too_well == 0 => {
                eprintln!("{at}: known gap now passes, take it off GAPS ({})", g.why)
            }
            _ => {}
        }
    }
    assert!(failed.is_empty(), "{failed:#?}");
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
    let clips = run(&matrix);
    let cells = clips.len() / READINGS.len();
    let missegmented = clips.iter().filter(|(_, _, k)| !k.segmented()).count();
    let too_well: usize = clips.iter().map(|(_, _, k)| k.graded_too_well()).sum();
    let ranked_wrong: usize = clips.iter().map(|(_, _, k)| k.ranked_wrong()).sum();
    eprintln!(
        "{cells} cells, {} clips: {missegmented} missegmented; of {} substitutions {too_well} \
         graded too well, {ranked_wrong} ranked above the spoken tone",
        clips.len(),
        clips.len() * 9
    );
}
