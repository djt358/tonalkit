//! `analyze`: PCM to [`Analysis`] (spec §4.1, §10, §12).

use tonekit_core::{
    Analysis, AssessError, F0Frame, F0Track, MeasureIssue, Register, RegisterSource, HOP,
    SAMPLE_RATE,
};
use tonekit_f0::{
    clipping_ratio, energy, fit_length, repair_octaves, repair_subharmonics, snr_db, sonority,
    F0Provider, Pyin,
};
use tonekit_segment::{boundaries_with, nuclei, speech_region, SegmentParams};
use tonekit_shape::{cold_register, is_cold, voiced_semitones};

/// `Clipped` fires when more than this fraction of samples has `|x| >= 0.99`.
const CLIPPED_ABOVE: f32 = 0.01;
/// `LowSnr` fires when the frame energies' `p95 - p10` is below this many dB.
const LOW_SNR_BELOW_DB: f32 = 10.0;
/// Provider name reported for a caller-supplied f0 track.
const EXTERNAL: &str = "external";
/// The longest input `analyze` accepts, in seconds (ruling R52): the dense pYIN's memory grows
/// with the length (about 500 MB at 120 s), which an iOS app cannot afford unbounded.
const MAX_SECONDS: u32 = 30;
/// A given register claiming more syllables than this is corrupted: 1 000 syllables a day for 27
/// years. Believing it would freeze the register, since each merge moves it `u/(n+u)` of the way.
const MAX_REGISTER_SYLLABLES: u32 = 10_000_000;
/// The band a believable register level lies in, in semitones re 55 Hz: about 14 Hz to 3.5 kHz,
/// far outside any voice (and pYIN's 50-600 Hz range) but still a pitch. A level beyond it is a
/// corrupted one, which would grade every syllable wrongly like a NaN does.
const REGISTER_ST_BAND: std::ops::RangeInclusive<f32> = -24.0..=72.0;

/// Where the f0 track comes from.
#[derive(Clone, Debug)]
pub enum F0Choice {
    /// The built-in pYIN provider.
    Pyin,
    /// A track computed elsewhere (a neural pitch model, say), one frame per 10 ms. It is
    /// sanitised first (R43): a non-finite or non-positive `hz` makes the frame unvoiced and a
    /// non-finite `voiced_p` becomes 0, then `voiced_p` is clamped to `[0, 1]`. It is trimmed or
    /// padded with unvoiced frames to the pipeline's frame count, and reported with provider
    /// `"external"`.
    External(F0Track),
}

/// Options for [`analyze`].
#[derive(Clone, Debug)]
pub struct AnalyzeOptions {
    pub f0: F0Choice,
}

impl Default for AnalyzeOptions {
    /// pYIN.
    fn default() -> Self {
        Self { f0: F0Choice::Pyin }
    }
}

/// A copy of an untrusted external `track` that is safe to analyse (ruling R43): a frame whose
/// `hz` is non-finite or not positive becomes unvoiced, and a non-finite `voiced_p` reads as 0,
/// then every `voiced_p` is clamped to `[0, 1]`. Everything downstream may then assume that a
/// voiced frame has a finite positive pitch.
fn sanitised(track: &F0Track) -> F0Track {
    F0Track {
        frames: track
            .frames
            .iter()
            .map(|frame| F0Frame {
                hz: frame.hz.filter(|hz| hz.is_finite() && *hz > 0.0),
                voiced_p: if frame.voiced_p.is_finite() {
                    frame.voiced_p.clamp(0.0, 1.0)
                } else {
                    0.0
                },
            })
            .collect(),
        provider: track.provider.clone(),
    }
}

/// Whether a caller's register can be graded against: every level finite and within
/// [`REGISTER_ST_BAND`], `floor <= median <= ceil` with the ceiling above the floor, and a
/// believable syllable count. Anything else (a corrupted persisted register, most likely) would
/// grade every syllable wrongly and be persisted again through `register_update`.
fn usable(r: &Register) -> bool {
    [r.floor_st, r.median_st, r.ceil_st]
        .iter()
        .all(|v| REGISTER_ST_BAND.contains(v))
        && r.floor_st <= r.median_st
        && r.median_st <= r.ceil_st
        && r.ceil_st > r.floor_st
        && r.n_syllables <= MAX_REGISTER_SYLLABLES
}

/// Analyses one utterance of 16 kHz mono `pcm`, once, for any number of `decode`, `lattice` and
/// `assess` calls.
///
/// 1. **f0**: pYIN or the sanitised external track, then subharmonic repair (ruling R60: a frame
///    whose signal repeats at half its tracked period is doubled, up to pYIN's 600 Hz ceiling)
///    and octave repair (run-local, ruling R32). Both repairs apply to an external track as they
///    do to pYIN's: subharmonic repair reads the signal, not the tracker, and any tracker can
///    lock onto half the pitch for a whole syllable. Subharmonic repair can change frames in a
///    run of any length (octave repair leaves runs under 5 frames alone). A voiced frame is one
///    with `hz.is_some()` everywhere.
/// 2. **Energy**, **sonority** (ruling R102: per frame, the share of the energy above 150 Hz that
///    lies below 2 kHz, which tells a vowel whose pitch was lost from a consonant) and the signal
///    issues: `Clipped` if more than 1% of samples have `|x| >= 0.99`,
///    `LowSnr` if the frame energies' `p95 - p10` is under 10 dB.
/// 3. **Segmentation** under the default [`SegmentParams`], used for every step (the parameters
///    must never be mixed): speech region, then nuclei and candidate boundaries inside it. No
///    region means no nuclei and no boundaries.
/// 4. **Register**: `register` if given (`Given`), flagged `ColdStartRegister` while it is
///    [cold](is_cold); otherwise the utterance's own cold-start register over its voiced
///    semitones (those in the speech region, or the whole track's when there is none), counting
///    the nuclei as its syllables (`ColdStart`, always flagged `ColdStartRegister`). A given
///    register that is not usable (a level that is not finite or outside -24 to 72 semitones, a
///    median outside the floor-to-ceiling range, a ceiling not above the floor, more than ten
///    million syllables) is replaced by that cold start and flagged `InvalidRegister` too: a
///    corrupted persisted register must not stop grading.
///
/// # Errors
///
/// - [`AssessError::EmptyAudio`] if `pcm` is empty (checked first);
/// - [`AssessError::UnsupportedSampleRate`] unless `sample_rate` is 16 000; the caller resamples;
/// - [`AssessError::TooLong`] for more than 30 s of audio (ruling R52), before any work.
///
/// Audio too short or too quiet to hold speech is not an error: it analyses to no speech, and
/// every syllable of any later `assess` is `NotMeasured`. Non-finite samples read as silence.
pub fn analyze(
    pcm: &[f32],
    sample_rate: u32,
    register: Option<&Register>,
    opts: &AnalyzeOptions,
) -> Result<Analysis, AssessError> {
    if pcm.is_empty() {
        return Err(AssessError::EmptyAudio);
    }
    if sample_rate != SAMPLE_RATE {
        return Err(AssessError::UnsupportedSampleRate { got: sample_rate });
    }
    if pcm.len() > (MAX_SECONDS * SAMPLE_RATE) as usize {
        return Err(AssessError::TooLong {
            seconds: pcm.len() as f32 / SAMPLE_RATE as f32,
            max: MAX_SECONDS as f32,
        });
    }

    let mut f0 = match &opts.f0 {
        F0Choice::Pyin => Pyin::default().track(pcm),
        F0Choice::External(track) => {
            let mut fitted = fit_length(sanitised(track), pcm.len() / HOP + 1);
            fitted.provider = EXTERNAL.to_owned();
            fitted
        }
    };
    repair_subharmonics(&mut f0, pcm, Pyin::default().fmax);
    repair_octaves(&mut f0);
    let energy = energy(pcm);
    let sonority = sonority(pcm);

    let mut issues = Vec::new();
    if clipping_ratio(pcm) > CLIPPED_ABOVE {
        issues.push(MeasureIssue::Clipped);
    }
    if snr_db(&energy) < LOW_SNR_BELOW_DB {
        issues.push(MeasureIssue::LowSnr);
    }

    let params = SegmentParams::default();
    let speech = speech_region(&energy, &params);
    let (nuclei, boundaries) = match &speech {
        Some(region) => {
            let found = nuclei(&energy, &f0, region, &params);
            let edges = boundaries_with(&energy, &f0, region, &found, &params);
            (found, edges)
        }
        None => (Vec::new(), Vec::new()),
    };
    let voiced_st = voiced_semitones(&f0, speech.as_ref());

    let register = match register {
        Some(given) if !usable(given) => {
            issues.push(MeasureIssue::InvalidRegister);
            None
        }
        other => other,
    };
    let (register, register_source) = match register {
        Some(given) => {
            if is_cold(given) {
                issues.push(MeasureIssue::ColdStartRegister);
            }
            (given.clone(), RegisterSource::Given)
        }
        None => {
            issues.push(MeasureIssue::ColdStartRegister);
            let syllables = u32::try_from(nuclei.len()).unwrap_or(u32::MAX);
            (
                cold_register(&voiced_st, syllables),
                RegisterSource::ColdStart,
            )
        }
    };

    Ok(Analysis {
        f0,
        energy,
        nuclei,
        boundaries,
        speech,
        register,
        register_source,
        voiced_st,
        issues,
        sonority,
    })
}
