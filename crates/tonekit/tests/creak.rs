//! A creaky phrase-final tone 3 is one syllable (ruling R58, fix round 1; spec §12: "T3 creak:
//! not penalised").
//!
//! Native speakers often go creaky at the bottom of a phrase-final tone 3 (水, 伞), and pYIN then
//! loses the pitch there for a few frames while the level barely moves. Before fix round 1, R58
//! split such a tone 3 at the dropout into two nuclei, and the closed-set decoder spent the extra
//! nucleus as an insertion that let a wrong tone on a neighbouring syllable outrank the spoken one.
//! A dropout inside one continuous contour must stay one nucleus: only a pitch break of 3
//! semitones or more across a gap separates two syllables.
//!
//! The clips: one, two and three syllables ending in a full tone 3 ([2,1,4], ruling R8), 250 ms
//! syllables by a 110–190 Hz speaker on a warm register, run together or with a 30 ms gap and a
//! 40 ms consonant, 30 dB SNR. pYIN's own track is used with a dropout of 3 to 8 frames forced
//! at the tone 3's bottom (the middle of its voiced part), and the level dips over the dropout by
//! up to 1.5 dB (a creak's quieter pulses, less than the 2 dB that separates two energy peaks).

mod sweep;

use sweep::{cmn, knots, substitutions, RATE};
use tonekit::{analyze, AnalyzeOptions, F0Choice, F0Track};
use tonekit_f0::{F0Provider, Pyin};
use tonekit_testkit::{register_for, synth, Synth, SynthSpec, SynthSyllable};

const SPEAKER: (f32, f32) = (110.0, 190.0);
const READINGS: [&[&str]; 3] = [&["3"], &["2", "3"], &["4", "1", "3"]];
/// Silence after each syllable but the last, and the unvoiced onset that goes with it.
const SPACINGS: [(f32, f32); 2] = [(0.0, 0.0), (30.0, 40.0)];
const DROPOUT_FRAMES: [usize; 4] = [3, 4, 6, 8];
const DIPS_DB: [f32; 3] = [0.0, 1.0, 1.5];

fn clip(reading: &[&str], (gap_ms, onset_ms): (f32, f32)) -> Synth {
    let last = reading.len() - 1;
    synth(&SynthSpec {
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
                gap_after_ms: if i == last { 0.0 } else { gap_ms },
                unvoiced_onset_ms: onset_ms,
                creak: None,
            })
            .collect(),
        snr_db: Some(30.0),
        seed: 1,
    })
}

/// The first frame of a `frames`-long dropout centred on the bottom of the last syllable's
/// [2,1,4] contour: the middle of its voiced part.
fn dropout_start(s: &Synth, onset_ms: f32, frames: usize) -> usize {
    let (start, end) = s.syllable_frames[s.syllable_frames.len() - 1];
    let voiced_start = start as usize + (onset_ms / 10.0).round() as usize;
    (voiced_start + end as usize) / 2 - frames / 2
}

/// `pcm` with a raised-cosine level dip of `dip_db` over frames `from..to` and 2 frames either
/// side, deepest in the middle.
fn dipped(pcm: &[f32], from: usize, to: usize, dip_db: f32) -> Vec<f32> {
    let (a, b) = (from.saturating_sub(2) * 160, (to + 2) * 160);
    pcm.iter()
        .enumerate()
        .map(|(j, &x)| {
            if !(a..b).contains(&j) {
                return x;
            }
            let u = (j - a) as f32 / (b - a) as f32;
            let depth = 0.5 * (1.0 - (std::f32::consts::TAU * u).cos());
            x * 10f32.powf(-dip_db * depth / 20.0)
        })
        .collect()
}

/// pYIN's track of `pcm` with no pitch on frames `from..to`.
fn creaky_track(pcm: &[f32], from: usize, to: usize) -> F0Track {
    let mut track = Pyin::default().track(pcm);
    for f in &mut track.frames[from..to] {
        f.hz = None;
        f.voiced_p = 0.1;
    }
    track
}

/// Every clip of `reading` (each spacing, dropout length and dip): one nucleus per syllable, and
/// every single full-tone substitution grades below the spoken tone on its syllable.
fn creaky_final_tone_3_is_one_nucleus(reading: &[&str]) {
    let pack = cmn();
    let register = register_for(SPEAKER.0, SPEAKER.1);
    let mut failed = Vec::new();
    let (mut clips, mut worst) = (0, (0.0_f32, String::new()));
    for spacing in SPACINGS {
        let s = clip(reading, spacing);
        for frames in DROPOUT_FRAMES {
            let from = dropout_start(&s, spacing.1, frames);
            let to = from + frames;
            for dip_db in DIPS_DB {
                let pcm = dipped(&s.pcm, from, to, dip_db);
                let opts = AnalyzeOptions {
                    f0: F0Choice::External(creaky_track(&pcm, from, to)),
                };
                let a = analyze(&pcm, RATE, Some(&register), &opts).unwrap();
                let subs = substitutions(&a, &pack, reading);
                let at = format!(
                    "{} (gap {} ms), dropout {frames} at {from}, dip {dip_db} dB",
                    reading.join("-"),
                    spacing.0
                );
                let nuclei: Vec<u32> = a.nuclei.iter().map(|n| n.frame).collect();
                let ranked_wrong: Vec<String> = subs
                    .iter()
                    .filter(|x| x.ranked_wrong())
                    .map(|x| x.describe())
                    .collect();
                if nuclei.len() != reading.len() || !ranked_wrong.is_empty() {
                    failed.push(format!("{at}: nuclei {nuclei:?}, {ranked_wrong:#?}"));
                }
                for x in &subs {
                    if x.p_wrong() > worst.0 {
                        worst = (x.p_wrong(), format!("{at}: {}", x.describe()));
                    }
                }
                clips += 1;
            }
        }
    }
    eprintln!(
        "{}: {} of {clips} creaky clips failed; highest wrong: {}",
        reading.join("-"),
        failed.len(),
        worst.1
    );
    assert!(
        failed.is_empty(),
        "{} of {clips}: {failed:#?}",
        failed.len()
    );
}

#[test]
fn a_creaky_lone_tone_3_is_one_nucleus() {
    creaky_final_tone_3_is_one_nucleus(READINGS[0]);
}

#[test]
fn a_creaky_tone_3_after_a_tone_2_is_one_nucleus_and_neither_tone_shifts() {
    creaky_final_tone_3_is_one_nucleus(READINGS[1]);
}

#[test]
fn a_creaky_tone_3_ending_three_syllables_is_one_nucleus_and_no_tone_shifts() {
    creaky_final_tone_3_is_one_nucleus(READINGS[2]);
}
