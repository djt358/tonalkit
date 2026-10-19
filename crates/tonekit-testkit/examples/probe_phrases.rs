//! Writes fluent synthetic phrases of 4 to 48 syllables as 16 kHz mono 16-bit WAVs, for the
//! harness's length probe (`harness/scripts/length_probe.py`, ruling R123): how `tkh fit`'s forced
//! decode and `tkh eval` cope with sentence-length clips from public corpora.
//!
//! `cargo run -p tonekit-testkit --example probe_phrases --release -- OUT_DIR` writes
//! `OUT_DIR/<id>.wav` and `OUT_DIR/phrases.tsv`: per phrase its id, speaker, declination in Chao,
//! the produced tones separated by spaces, and each syllable's true `start:end` frames (half-open,
//! on the 10 ms grid) separated by spaces.
//!
//! Each phrase is spoken at 5 syllables a second with full tones only (ruling R8's knots, a final
//! T3 rising) and no 3-3 pair; a third of the syllables open on fricative noise and the rest are
//! joined by voiced glides with a 3 dB dip, as in the fluent-speech sweep. Every phrase comes
//! twice: level, and with declination, its pitch sinking linearly by one Chao step from the first
//! syllable to the last, as read sentences drift down. Deterministic.

use std::fs;
use std::io::{self, Write};
use std::path::Path;

use tonekit_testkit::{synth_fluent, FluentSpec, FluentSyllable, Rng, Speaker, FLUENT_SPEAKERS};

const LENGTHS: [usize; 7] = [4, 8, 12, 16, 24, 32, 48];
const SEEDS_PER_SPEAKER: u64 = 6;
const DECLINATIONS: [f32; 2] = [0.0, 1.0];
const SYLLABLES_PER_S: f32 = 5.0;
const RATE: u32 = 16_000;

/// Ruling R8's knots: "3" dips and stays low inside a phrase and rises at its end.
fn knots(tone: u8, last: bool) -> Vec<f32> {
    match (tone, last) {
        (1, _) => vec![5.0, 5.0],
        (2, _) => vec![3.0, 5.0],
        (3, true) => vec![2.0, 1.0, 4.0],
        (3, false) => vec![2.0, 1.0],
        _ => vec![5.0, 1.0],
    }
}

/// `n` full tones with no 3 right after a 3 (third-tone sandhi is not what the probe measures).
fn tones(rng: &mut Rng, n: usize) -> Vec<u8> {
    let mut out: Vec<u8> = Vec::with_capacity(n);
    while out.len() < n {
        let tone = 1 + (rng.next_u64() % 4) as u8;
        if !(tone == 3 && out.last() == Some(&3)) {
            out.push(tone);
        }
    }
    out
}

/// Whether each syllable opens on fricative noise (a third of them, at random).
fn onsets(rng: &mut Rng, n: usize) -> Vec<bool> {
    (0..n).map(|_| rng.next_u64() % 3 == 0).collect()
}

fn syllables(tones: &[u8], onsets: &[bool], declination: f32) -> Vec<FluentSyllable> {
    let last = tones.len().saturating_sub(1).max(1) as f32;
    tones
        .iter()
        .zip(onsets)
        .enumerate()
        .map(|(i, (&tone, &noisy))| FluentSyllable {
            chao: knots(tone, i == tones.len() - 1)
                .into_iter()
                .map(|c| c - declination * i as f32 / last)
                .collect(),
            dur_ms: 1000.0 / SYLLABLES_PER_S,
            unvoiced_onset_ms: if noisy { 40.0 } else { 0.0 },
        })
        .collect()
}

fn wav_bytes(pcm: &[f32]) -> Vec<u8> {
    let data_len = (pcm.len() * 2) as u32;
    let mut out = Vec::with_capacity(44 + pcm.len() * 2);
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&(36 + data_len).to_le_bytes());
    out.extend_from_slice(b"WAVEfmt ");
    out.extend_from_slice(&16_u32.to_le_bytes());
    out.extend_from_slice(&1_u16.to_le_bytes()); // PCM
    out.extend_from_slice(&1_u16.to_le_bytes()); // mono
    out.extend_from_slice(&RATE.to_le_bytes());
    out.extend_from_slice(&(RATE * 2).to_le_bytes());
    out.extend_from_slice(&2_u16.to_le_bytes());
    out.extend_from_slice(&16_u16.to_le_bytes());
    out.extend_from_slice(b"data");
    out.extend_from_slice(&data_len.to_le_bytes());
    for x in pcm {
        let sample = (x.clamp(-1.0, 1.0) * 32767.0).round() as i16;
        out.extend_from_slice(&sample.to_le_bytes());
    }
    out
}

/// One phrase: its WAV, and its line of the index.
fn phrase(out: &Path, speaker: &Speaker, n: usize, k: u64, declination: f32) -> io::Result<String> {
    let seed = 1000 * n as u64 + 10 * k + 1;
    let mut rng = Rng::new(seed);
    let tones = tones(&mut rng, n);
    let onsets = onsets(&mut rng, n);
    let synth = synth_fluent(&FluentSpec {
        floor_hz: speaker.floor_hz,
        ceil_hz: speaker.ceil_hz,
        lead_ms: 300.0,
        tail_ms: 300.0,
        syllables: syllables(&tones, &onsets, declination),
        glide_ms: 40.0,
        dip_db: 3.0,
        dip_ms: 80.0,
        snr_db: None,
        seed,
    });
    let id = format!("len{n:02}-{}-{k}-decl{declination}", speaker.name);
    fs::write(out.join(format!("{id}.wav")), wav_bytes(&synth.pcm))?;
    let spoken: Vec<String> = tones.iter().map(u8::to_string).collect();
    let frames: Vec<String> = synth
        .syllable_frames
        .iter()
        .map(|(start, end)| format!("{start}:{end}"))
        .collect();
    Ok(format!(
        "{id}\t{}\t{declination}\t{}\t{}",
        speaker.name,
        spoken.join(" "),
        frames.join(" ")
    ))
}

fn main() -> io::Result<()> {
    let out = std::env::args().nth(1).ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "usage: probe_phrases OUT_DIR")
    })?;
    let out = Path::new(&out);
    fs::create_dir_all(out)?;
    let mut index = fs::File::create(out.join("phrases.tsv"))?;
    for n in LENGTHS {
        for speaker in &FLUENT_SPEAKERS {
            for k in 0..SEEDS_PER_SPEAKER {
                for declination in DECLINATIONS {
                    writeln!(index, "{}", phrase(out, speaker, n, k, declination)?)?;
                }
            }
        }
    }
    Ok(())
}
