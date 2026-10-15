//! Report only (fix round 1, item 6): how often fluent synthetic phrases land on the floor that
//! decided the first volunteer bundles, a syllable no nucleus could hold.
//!
//! That floor is the closed-set decoder's "likely miss" (ruling R33): when the analysis has fewer
//! usable syllable anchors than the reading has syllables (nuclei, and since ruling R102 the count
//! stage's unpitched and joined-syllable candidates), the relaxed pass (or, with no path at all,
//! the no-path fallback) leaves a syllable without one. Its path scores `unvoiced_syllable_llr`
//! (−3.0 in `cmn.calib.json`); it used to be reported `Partial { [Unvoiced] }` and counted in
//! `overall` at `sigmoid(−3.0)` = 0.047, and is now `NotMeasured { NoNucleus }`, which leaves the
//! clip unscored (ruling R104).
//!
//! The phrases are 一 + measure word + noun as native speakers run them together: 一 short (0.75 of
//! a syllable) with a reduced fall (yì, Chao 5 → 2) or rise (yí, 3 → 4.5), the measure word full,
//! the noun lengthened (1.25) and phrase-final, consonants as fricative noise of their usual length
//! and sonorants (l, r, y) as voiced joins. Run with `--ignored --nocapture`.

mod sweep;

use sweep::{assess_reading, cmn, knots, RATE};
use tonekit::{analyze, AnalyzeOptions, MeasureIssue, Measured};
use tonekit_testkit::{synth_fluent, FluentSpec, FluentSyllable, FLUENT_SPEAKERS};

/// A phrase: its characters, the tones produced (sandhi applied), and each syllable's unvoiced
/// onset in ms (0: none, or a voiced consonant).
struct Phrase {
    text: &'static str,
    tones: [&'static str; 3],
    onsets_ms: [f32; 3],
}

const PHRASES: [Phrase; 8] = [
    Phrase {
        text: "一张纸",
        tones: ["4", "1", "3"],
        onsets_ms: [0.0, 30.0, 30.0],
    },
    Phrase {
        text: "一条鱼",
        tones: ["4", "2", "2"],
        onsets_ms: [0.0, 40.0, 0.0],
    },
    Phrase {
        text: "一把伞",
        tones: ["4", "2", "3"],
        onsets_ms: [0.0, 15.0, 40.0],
    },
    Phrase {
        text: "一块钱",
        tones: ["2", "4", "2"],
        onsets_ms: [0.0, 40.0, 40.0],
    },
    Phrase {
        text: "一辆车",
        tones: ["2", "4", "1"],
        onsets_ms: [0.0, 0.0, 40.0],
    },
    Phrase {
        text: "一杯水",
        tones: ["4", "1", "3"],
        onsets_ms: [0.0, 15.0, 40.0],
    },
    Phrase {
        text: "一瓶水",
        tones: ["4", "2", "3"],
        onsets_ms: [0.0, 40.0, 40.0],
    },
    Phrase {
        text: "一个人",
        tones: ["2", "4", "2"],
        onsets_ms: [0.0, 15.0, 0.0],
    },
];

/// The Chao knots and length factor of syllable `i` of a phrase.
fn spoken(tone: &str, i: usize) -> (Vec<f32>, f32) {
    match (i, tone) {
        (0, "4") => (vec![5.0, 2.0], 0.75),
        (0, "2") => (vec![3.0, 4.5], 0.75),
        (2, t) => (knots(t, true), 1.25),
        (_, t) => (knots(t, false), 1.0),
    }
}

/// What landed where in one group of clips.
#[derive(Default)]
struct Tally {
    clips: usize,
    missegmented: usize,
    floor_syllables: usize,
    floor_clips: usize,
    other_partial_without_distance: usize,
}

#[test]
#[ignore = "report only: fluent phrases on the 0.047 floor are measured, not asserted"]
fn fluent_phrases_on_the_missing_syllable_floor_report() {
    let pack = cmn();
    let mut total = Tally::default();
    for rate in [5.0_f32, 6.0] {
        for dip_db in [0.0_f32, 3.0, 6.0] {
            for snr_db in [None, Some(20.0_f32)] {
                let mut t = Tally::default();
                for speaker in &FLUENT_SPEAKERS {
                    for phrase in &PHRASES {
                        let syllables = phrase
                            .tones
                            .iter()
                            .enumerate()
                            .map(|(i, tone)| {
                                let (chao, factor) = spoken(tone, i);
                                FluentSyllable {
                                    chao,
                                    dur_ms: factor * 1000.0 / rate,
                                    unvoiced_onset_ms: phrase.onsets_ms[i],
                                }
                            })
                            .collect();
                        let pcm = synth_fluent(&FluentSpec {
                            floor_hz: speaker.floor_hz,
                            ceil_hz: speaker.ceil_hz,
                            lead_ms: 200.0,
                            tail_ms: 200.0,
                            syllables,
                            glide_ms: 40.0,
                            dip_db,
                            dip_ms: 80.0,
                            snr_db,
                            seed: 1,
                        })
                        .pcm;
                        let a = analyze(
                            &pcm,
                            RATE,
                            Some(&speaker.register()),
                            &AnalyzeOptions::default(),
                        )
                        .unwrap();
                        let u = assess_reading(&a, &pack, &phrase.tones);
                        let mut floors = 0;
                        for s in &u.syllables {
                            match &s.measured {
                                Measured::NotMeasured {
                                    issue: MeasureIssue::NoNucleus,
                                } => floors += 1,
                                Measured::Partial { .. } if s.distance.is_none() => {
                                    t.other_partial_without_distance += 1
                                }
                                _ => {}
                            }
                        }
                        let missegmented = a.nuclei.len() != 3;
                        if missegmented || floors > 0 {
                            eprintln!(
                                "  {} {} {rate}/s {dip_db} dB {snr_db:?}: nuclei {:?}, p {:?}",
                                speaker.name,
                                phrase.text,
                                a.nuclei.iter().map(|n| n.frame).collect::<Vec<_>>(),
                                u.syllables
                                    .iter()
                                    .map(|s| (s.p_correct * 1000.0).round() / 1000.0)
                                    .collect::<Vec<_>>()
                            );
                        }
                        t.clips += 1;
                        t.missegmented += usize::from(missegmented);
                        t.floor_syllables += floors;
                        t.floor_clips += usize::from(floors > 0);
                    }
                }
                eprintln!(
                    "{rate} syl/s, {dip_db} dB dip, SNR {snr_db:?}: {} clips, {} missegmented, \
                     {} on the floor ({} syllables), {} other Partial without a distance",
                    t.clips,
                    t.missegmented,
                    t.floor_clips,
                    t.floor_syllables,
                    t.other_partial_without_distance
                );
                total.clips += t.clips;
                total.missegmented += t.missegmented;
                total.floor_syllables += t.floor_syllables;
                total.floor_clips += t.floor_clips;
                total.other_partial_without_distance += t.other_partial_without_distance;
            }
        }
    }
    eprintln!(
        "all: {} clips, {} missegmented, {} on the floor ({} syllables), {} other Partial without \
         a distance",
        total.clips,
        total.missegmented,
        total.floor_clips,
        total.floor_syllables,
        total.other_partial_without_distance
    );
}
