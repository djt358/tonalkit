//! UniFFI surface of tonekit: the same compiled library the Rust tests exercise, callable from
//! Swift (spec §4.3). It is a thin layer over the [`tonekit`] facade:
//!
//! - [`Pack`] (a Swift class): `Pack.fromToml(packToml:calibJson:)`, then `lect()`,
//!   `baseAccent()` and `inventory()`;
//! - [`analyze`], [`decode`], [`lattice`] and [`assess`] (Swift free functions) with the facade's
//!   own types, which carry UniFFI derives under the `ffi` feature: there are no mirror types.
//!   `AssessRequest` and the ids are the facade's; in Swift the four id types (`Lect`, `AccentId`,
//!   `ToneId`, `CandidateId`) are plain `String`s.
//!
//! Every function returns `Result<_, AssessError>`, which Swift sees as a thrown `AssessError`; a
//! pack the library rejects is `AssessError.Pack(message:)`, a request that cannot be graded
//! (no candidates, a candidate with no targets) `AssessError.InvalidRequest(message:)`, and audio
//! over 30 s `AssessError.TooLong(seconds:max:)`. Bad input comes back as such an error, not a
//! panic (and UniFFI turns any panic into a thrown internal error, never a crash). An external f0
//! track is sanitised inside `analyze` (ruling R43): Swift may pass any floats, and a register
//! that is not usable is replaced by a cold start, flagged `InvalidRegister`.
//!
//! The crate builds as `staticlib` (the iOS XCFramework), `cdylib` (the host build that the
//! bindings generator reads) and `lib` (Rust tests). Build steps are in `scripts/`.
//!
//! The functions take their arguments by value because that is what crosses the FFI boundary:
//! Swift hands over owned copies, and UniFFI lifts them into owned Rust values.

#![forbid(unsafe_code)]

use std::sync::Arc;

use tonekit::{
    AccentId, Analysis, AnalyzeOptions, AssessError, AssessRequest, Candidate, DecodeResult,
    F0Choice, F0Track, GradingTarget, LanguagePack, Lect, Register, ToneId, ToneLattice,
    UtteranceAssessment,
};

uniffi::setup_scaffolding!();

/// A validated language pack plus its calibration (a Swift class; immutable, so it is safe to
/// share across threads and to keep for the life of the app).
#[derive(uniffi::Object)]
pub struct Pack {
    inner: LanguagePack,
}

#[uniffi::export]
impl Pack {
    /// Loads a pack from its TOML text and, optionally, its calibration JSON (the pack's own
    /// seeds when `nil`).
    ///
    /// Swift: `try Pack.fromToml(packToml: toml, calibJson: json)`.
    ///
    /// # Errors
    ///
    /// [`AssessError::Pack`] with the loader's message if either text is malformed or breaks a
    /// pack rule.
    #[uniffi::constructor(default(calib_json = None))]
    pub fn from_toml(
        pack_toml: String,
        calib_json: Option<String>,
    ) -> Result<Arc<Self>, AssessError> {
        LanguagePack::from_toml(&pack_toml, calib_json.as_deref())
            .map(|inner| Arc::new(Self { inner }))
            .map_err(|e| AssessError::Pack {
                message: e.to_string(),
            })
    }

    /// The language variety, ISO 639-3 (`"cmn"`).
    pub fn lect(&self) -> Lect {
        self.inner.lect().clone()
    }

    /// The accent to grade against when the caller has no preference (`"cmn-standard"`).
    pub fn base_accent(&self) -> AccentId {
        self.inner.base_accent().clone()
    }

    /// The tone ids of the pack, in pack order (`["1", "2", "3", "4", "5"]` for cmn).
    pub fn inventory(&self) -> Vec<ToneId> {
        self.inner.inventory().to_vec()
    }
}

/// Analyses one utterance of 16 kHz mono `pcm` (floats in -1..1), once, for any number of
/// `decode`, `lattice` and `assess` calls.
///
/// `register` is the speaker's stored pitch register (`nil` for a cold start).
/// `external_f0` replaces the built-in pYIN tracker with a pitch track computed elsewhere, one
/// frame per 10 ms; it is sanitised first, so any floats are safe (ruling R43).
///
/// # Errors
///
/// [`AssessError::EmptyAudio`] for no samples, [`AssessError::UnsupportedSampleRate`] unless
/// `sample_rate` is 16 000 (the caller resamples), and [`AssessError::TooLong`] for more than
/// 30 s of audio.
#[uniffi::export(default(register = None, external_f0 = None))]
pub fn analyze(
    pcm: Vec<f32>,
    sample_rate: u32,
    register: Option<Register>,
    external_f0: Option<F0Track>,
) -> Result<Analysis, AssessError> {
    let options = AnalyzeOptions {
        f0: external_f0.map_or(F0Choice::Pyin, F0Choice::External),
    };
    tonekit::analyze(&pcm, sample_rate, register.as_ref(), &options)
}

/// Scores candidate readings (of any syllable count) against an analysed utterance, best first.
///
/// # Errors
///
/// [`AssessError::InvalidRequest`] (an empty candidate set, a candidate with no targets),
/// [`AssessError::UnknownTone`], [`AssessError::DuplicateCandidate`] or [`AssessError::Pack`]
/// (an unknown accent).
#[uniffi::export]
pub fn decode(
    analysis: Analysis,
    pack: Arc<Pack>,
    grading: GradingTarget,
    candidates: Vec<Candidate>,
) -> Result<DecodeResult, AssessError> {
    tonekit::decode(&analysis, &pack.inner, &grading, &candidates)
}

/// The open-set tone lattice: per-syllable likelihoods over the pack's inventory, with no
/// candidates at all.
///
/// # Errors
///
/// [`AssessError::Pack`] if the pack rejects `grading` (an unknown accent).
#[uniffi::export]
pub fn lattice(
    analysis: Analysis,
    pack: Arc<Pack>,
    grading: GradingTarget,
) -> Result<ToneLattice, AssessError> {
    tonekit::lattice(&analysis, &pack.inner, &grading)
}

/// Grades the intended reading in `request` against an analysed utterance.
///
/// # Errors
///
/// [`AssessError::DuplicateCandidate`], [`AssessError::EvidenceLengthMismatch`],
/// [`AssessError::InvalidRequest`], [`AssessError::UnknownTone`] or [`AssessError::Pack`].
#[uniffi::export]
pub fn assess(
    analysis: Analysis,
    pack: Arc<Pack>,
    request: AssessRequest,
) -> Result<UtteranceAssessment, AssessError> {
    tonekit::assess(&analysis, &pack.inner, &request)
}
