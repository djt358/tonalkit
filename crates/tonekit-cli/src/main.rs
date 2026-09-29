//! `tonekit`: grade a WAV file's lexical tones, or print its open tone lattice, for quick local
//! checks. Exit codes: 0 success, 1 failure (unreadable input, pack or assessment error), 2 usage
//! (bad arguments, or a WAV that is not 16 kHz mono PCM16/float).

#![forbid(unsafe_code)]

mod args;
mod table;
mod wav;

use std::fmt;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use clap::Parser;
use tonekit::{
    analyze, assess, lattice, AccentId, Analysis, AnalyzeOptions, AssessRequest, Candidate,
    CandidateId, GradingTarget, LanguagePack, ToneId, ToneTarget, SAMPLE_RATE,
};

use crate::args::{AssessArgs, Cli, Command, Input, LatticeArgs};

/// Id of the reading the speaker was aiming for; distractors are `d1`, `d2`, ...
const INTENDED_ID: &str = "intended";

/// Why the run stopped, and with which exit code.
#[derive(Debug)]
pub enum CliError {
    /// The invocation is wrong: exit 2.
    Usage(String),
    /// The invocation is fine but the work failed: exit 1.
    Failure(String),
}

impl CliError {
    fn exit_code(&self) -> u8 {
        match self {
            Self::Usage(_) => 2,
            Self::Failure(_) => 1,
        }
    }
}

impl fmt::Display for CliError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Usage(m) | Self::Failure(m) => f.write_str(m),
        }
    }
}

fn main() -> ExitCode {
    match run(Cli::parse()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("tonekit: {e}");
            ExitCode::from(e.exit_code())
        }
    }
}

fn run(cli: Cli) -> Result<(), CliError> {
    match cli.command {
        Command::Assess(args) => run_assess(&args),
        Command::Lattice(args) => run_lattice(&args),
    }
}

fn run_assess(args: &AssessArgs) -> Result<(), CliError> {
    let intended = candidate(INTENDED_ID, "--tones", &args.tones, args.labels.as_deref())?;
    let mut distractors = Vec::with_capacity(args.distractors.len());
    for (n, tones) in args.distractors.iter().enumerate() {
        distractors.push(candidate(&format!("d{}", n + 1), "--distractor", tones, None)?);
    }
    let labels: Vec<Option<String>> = intended.targets.iter().map(|t| t.label.clone()).collect();

    let (pack, analysis) = load(&args.input)?;
    let request = AssessRequest {
        grading: grading(&pack, &args.input),
        intended,
        distractors,
        external: Vec::new(),
        compare_accents: args
            .compare_accents
            .iter()
            .map(|a| AccentId(a.clone()))
            .collect(),
    };
    let assessment = assess(&analysis, &pack, &request).map_err(failure)?;
    if args.input.json {
        emit(&serde_json::to_string_pretty(&assessment).map_err(json_error)?)
    } else {
        emit(&table::assessment(&assessment, &labels))
    }
}

fn run_lattice(args: &LatticeArgs) -> Result<(), CliError> {
    let (pack, analysis) = load(&args.input)?;
    let lattice = lattice(&analysis, &pack, &grading(&pack, &args.input)).map_err(failure)?;
    if args.input.json {
        emit(&serde_json::to_string_pretty(&lattice).map_err(json_error)?)
    } else {
        emit(&table::lattice(&lattice))
    }
}

/// Reads the WAV and the pack, and analyses the audio from a cold-start register.
fn load(input: &Input) -> Result<(LanguagePack, Analysis), CliError> {
    let pcm = wav::read_mono_16k(&input.wav)?;
    let pack = load_pack(&input.pack, input.calib.as_deref())?;
    let analysis = analyze(&pcm, SAMPLE_RATE, None, &AnalyzeOptions::default()).map_err(failure)?;
    Ok((pack, analysis))
}

fn load_pack(pack: &Path, calib: Option<&Path>) -> Result<LanguagePack, CliError> {
    let toml = read_text(pack)?;
    let calib_path = match calib {
        Some(explicit) => Some(explicit.to_path_buf()),
        None => Some(sibling_calibration(pack)).filter(|p| p.is_file()),
    };
    let calib_json = calib_path.as_deref().map(read_text).transpose()?;
    LanguagePack::from_toml(&toml, calib_json.as_deref())
        .map_err(|e| CliError::Failure(format!("{}: {e}", pack.display())))
}

/// `packs/cmn/cmn.toml` -> `packs/cmn/cmn.calib.json`.
fn sibling_calibration(pack: &Path) -> PathBuf {
    pack.with_extension("calib.json")
}

fn read_text(path: &Path) -> Result<String, CliError> {
    fs::read_to_string(path).map_err(|e| CliError::Failure(format!("{}: {e}", path.display())))
}

/// The accent to grade against: `--accent`, else the pack's base accent. No imprint style.
fn grading(pack: &LanguagePack, input: &Input) -> GradingTarget {
    GradingTarget {
        accent: input
            .accent
            .as_ref()
            .map_or_else(|| pack.base_accent().clone(), |a| AccentId(a.clone())),
        style: None,
        style_weight: 0.0,
    }
}

/// A candidate reading from a whitespace-separated tone list, labelled from `labels` if given.
fn candidate(
    id: &str,
    flag: &str,
    tones: &str,
    labels: Option<&str>,
) -> Result<Candidate, CliError> {
    let tones: Vec<&str> = tones.split_whitespace().collect();
    if tones.is_empty() {
        return Err(CliError::Usage(format!("{flag} needs at least one tone id")));
    }
    let labels: Vec<Option<String>> = match labels {
        None => vec![None; tones.len()],
        Some(text) => {
            let words: Vec<&str> = text.split_whitespace().collect();
            if words.len() != tones.len() {
                return Err(CliError::Usage(format!(
                    "--labels has {} labels but {flag} has {} tones",
                    words.len(),
                    tones.len()
                )));
            }
            words.into_iter().map(|w| Some(w.to_owned())).collect()
        }
    };
    Ok(Candidate {
        id: CandidateId(id.to_owned()),
        targets: tones
            .into_iter()
            .zip(labels)
            .map(|(tone, label)| ToneTarget {
                tone: ToneId(tone.to_owned()),
                lexical_variants: Vec::new(),
                label,
            })
            .collect(),
    })
}

fn json_error(e: serde_json::Error) -> CliError {
    CliError::Failure(format!("json: {e}"))
}

fn failure(e: impl fmt::Display) -> CliError {
    CliError::Failure(e.to_string())
}

/// Writes `text` (plus a newline unless it has one) to stdout.
fn emit(text: &str) -> Result<(), CliError> {
    let mut out = std::io::stdout().lock();
    out.write_all(text.as_bytes())
        .and_then(|()| if text.ends_with('\n') { Ok(()) } else { out.write_all(b"\n") })
        .and_then(|()| out.flush())
        .map_err(|e| CliError::Failure(format!("stdout: {e}")))
}
