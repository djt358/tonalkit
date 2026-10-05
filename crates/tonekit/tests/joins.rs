//! Ruling R61 (fix round 1): only a coarticulated join between two voiced syllables trims a
//! tone's edge frames; a voiceless consonant before a vowel does not.
//!
//! Each TBU's shape in the lattice is compared with the shape of the same nucleus measured with
//! no edge trimmed (`Joins::NONE`) or with a given edge trimmed.

mod sweep;

use sweep::{cmn, knots, RATE, READINGS};
use tonekit::{analyze, lattice, AccentId, Analysis, AnalyzeOptions, GradingTarget, ToneShape};
use tonekit_shape::{extract_nucleus, Joins};
use tonekit_testkit::{
    register_for, synth, synth_fluent, FluentSpec, FluentSyllable, SynthSpec, SynthSyllable,
};

const SPEAKER: (f32, f32) = (110.0, 190.0);

/// Each TBU's shape as the lattice measured it, beside the same nucleus's shape under each
/// `Joins` (none, start only, end only, both).
fn shapes(a: &Analysis) -> Vec<(Option<ToneShape>, [Option<ToneShape>; 4])> {
    let g = GradingTarget {
        accent: AccentId("cmn-standard".into()),
        style: None,
        style_weight: 0.0,
    };
    let l = lattice(a, &cmn(), &g).unwrap();
    let mut nuclei: Vec<u32> = a.nuclei.iter().map(|n| n.frame).collect();
    nuclei.sort_unstable();
    nuclei.dedup();
    assert_eq!(nuclei.len(), l.tbus.len());
    l.tbus
        .iter()
        .zip(nuclei)
        .map(|(t, n)| {
            let under = |start, end| {
                extract_nucleus(&a.f0, &t.span, n, &a.register, Joins { start, end })
                    .ok()
                    .map(|e| e.shape)
            };
            (
                t.shape.clone(),
                [
                    under(false, false),
                    under(true, false),
                    under(false, true),
                    under(true, true),
                ],
            )
        })
        .collect()
}

#[test]
fn a_voiceless_onset_after_a_pause_is_not_a_join() {
    // The P0 sweep's hardest condition: 30 ms of silence, then a 40 ms voiceless onset, at 25 dB
    // SNR. Before fix round 1, 2-4-1's tone 2 and tone 1 onsets were trimmed as joins.
    let register = register_for(SPEAKER.0, SPEAKER.1);
    for reading in READINGS {
        let last = reading.len() - 1;
        let s = synth(&SynthSpec {
            floor_hz: SPEAKER.0,
            ceil_hz: SPEAKER.1,
            lead_ms: 200.0,
            tail_ms: 200.0,
            syllables: reading
                .iter()
                .enumerate()
                .map(|(i, tone)| SynthSyllable {
                    chao: knots(tone, i == last),
                    dur_ms: 250.0,
                    gap_after_ms: if i == last { 0.0 } else { 30.0 },
                    unvoiced_onset_ms: 40.0,
                    creak: None,
                })
                .collect(),
            snr_db: Some(25.0),
            seed: 1,
        });
        let a = analyze(&s.pcm, RATE, Some(&register), &AnalyzeOptions::default()).unwrap();
        for (k, (got, under)) in shapes(&a).into_iter().enumerate() {
            assert_eq!(got, under[0], "{}: syllable {k} trimmed", reading.join("-"));
        }
    }
}

/// A fluent 3-syllable clip at 5 syllables/s, with a `onset_ms` fricative before the middle
/// syllable (0 for none).
fn fluent(reading: [&str; 3], dip_db: f32, onset_ms: f32) -> Vec<f32> {
    synth_fluent(&FluentSpec {
        floor_hz: SPEAKER.0,
        ceil_hz: SPEAKER.1,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: reading
            .iter()
            .enumerate()
            .map(|(i, tone)| FluentSyllable {
                unvoiced_onset_ms: if i == 1 { onset_ms } else { 0.0 },
                ..FluentSyllable::at_rate(knots(tone, i == 2), 5.0)
            })
            .collect(),
        glide_ms: 60.0,
        dip_db,
        dip_ms: 80.0,
        snr_db: None,
        seed: 1,
    })
    .pcm
}

#[test]
fn a_fricative_onset_in_fluent_speech_is_not_a_join() {
    let register = register_for(SPEAKER.0, SPEAKER.1);
    for reading in READINGS {
        // A 30 ms fricative before the middle syllable: its start is not trimmed (its end may be).
        let pcm = fluent(reading, 6.0, 30.0);
        let a = analyze(&pcm, RATE, Some(&register), &AnalyzeOptions::default()).unwrap();
        let tbus = shapes(&a);
        assert_eq!(tbus.len(), 3, "{}", reading.join("-"));
        let (got, under) = &tbus[1];
        assert!(
            got == &under[0] || got == &under[2],
            "{}: the middle syllable's fricative onset was trimmed",
            reading.join("-")
        );
    }
}

#[test]
fn a_voiced_join_the_pitch_glides_through_is_still_trimmed() {
    // What R61 is for: a tone 2 after a tone 1 with no consonant between them, the pitch gliding
    // down into the tone 2's start. Both sides of that join are left out.
    let register = register_for(SPEAKER.0, SPEAKER.1);
    for (reading, join) in [(["1", "2", "3"], 0), (["4", "1", "2"], 1)] {
        let pcm = fluent(reading, 6.0, 0.0);
        let a = analyze(&pcm, RATE, Some(&register), &AnalyzeOptions::default()).unwrap();
        let tbus = shapes(&a);
        assert_eq!(tbus.len(), 3, "{}", reading.join("-"));
        let (left, left_under) = &tbus[join];
        let (right, right_under) = &tbus[join + 1];
        assert!(
            left == &left_under[2] || left == &left_under[3],
            "{}: the tone 1's end was not trimmed",
            reading.join("-")
        );
        assert!(
            right == &right_under[1] || right == &right_under[3],
            "{}: the tone 2's start was not trimmed",
            reading.join("-")
        );
    }
}
