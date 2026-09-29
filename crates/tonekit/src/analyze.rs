//! `analyze`: PCM to [`Analysis`] (spec §4.1, §10, §12).

use tonekit_core::{
    Analysis, AssessError, F0Frame, F0Track, MeasureIssue, Register, RegisterSource, HOP,
    SAMPLE_RATE,
};
use tonekit_f0::{clipping_ratio, energy, fit_length, repair_octaves, snr_db, F0Provider, Pyin};
use tonekit_segment::{boundaries_with, nuclei, speech_region, SegmentParams};
use tonekit_shape::{cold_register, is_cold, voiced_semitones};

/// `Clipped` fires when more than this fraction of samples has `|x| >= 0.99`.
const CLIPPED_ABOVE: f32 = 0.01;
/// `LowSnr` fires when the frame energies' `p95 - p10` is below this many dB.
const LOW_SNR_BELOW_DB: f32 = 10.0;
/// Provider name reported for a caller-supplied f0 track.
const EXTERNAL: &str = "external";

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

/// Analyses one utterance of 16 kHz mono `pcm`, once, for any number of `decode`, `lattice` and
/// `assess` calls.
///
/// 1. **f0**: pYIN or the sanitised external track, then octave repair (run-local, ruling R32).
///    A voiced frame is one with `hz.is_some()` everywhere.
/// 2. **Energy** and the signal issues: `Clipped` if more than 1% of samples have `|x| >= 0.99`,
///    `LowSnr` if the frame energies' `p95 - p10` is under 10 dB.
/// 3. **Segmentation** under the default [`SegmentParams`], used for every step (the parameters
///    must never be mixed): speech region, then nuclei and candidate boundaries inside it. No
///    region means no nuclei and no boundaries.
/// 4. **Register**: `register` if given (`Given`), flagged `ColdStartRegister` while it is
///    [cold](is_cold); otherwise the utterance's own cold-start register over the voiced
///    semitones in the speech region, counting the nuclei as its syllables (`ColdStart`, always
///    flagged `ColdStartRegister`).
///
/// # Errors
///
/// - [`AssessError::EmptyAudio`] if `pcm` is empty (checked first);
/// - [`AssessError::UnsupportedSampleRate`] unless `sample_rate` is 16 000; the caller resamples.
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

    let mut f0 = match &opts.f0 {
        F0Choice::Pyin => Pyin::default().track(pcm),
        F0Choice::External(track) => {
            let mut fitted = fit_length(sanitised(track), pcm.len() / HOP + 1);
            fitted.provider = EXTERNAL.to_owned();
            fitted
        }
    };
    repair_octaves(&mut f0);
    let energy = energy(pcm);

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
    })
}
