//! Command line: `tonekit assess` and `tonekit lattice`.

use std::path::PathBuf;

use clap::{Args, Parser, Subcommand};

/// Quick local tone checks on 16 kHz mono WAV files.
#[derive(Debug, Parser)]
#[command(name = "tonekit", version, about)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Grade an intended reading of the utterance, one row per syllable.
    Assess(AssessArgs),
    /// Print the open tone lattice: per-syllable tone likelihoods, no intended reading.
    Lattice(LatticeArgs),
}

/// What both commands need to load and analyse an utterance.
#[derive(Debug, Args)]
pub struct Input {
    /// 16 kHz mono WAV, PCM16 or 32-bit float.
    pub wav: PathBuf,
    /// Language pack TOML, e.g. packs/cmn/cmn.toml.
    #[arg(long)]
    pub pack: PathBuf,
    /// Calibration JSON. Default: `<pack stem>.calib.json` beside the pack if it exists,
    /// else the built-in seeds.
    #[arg(long)]
    pub calib: Option<PathBuf>,
    /// Accent to grade against. Default: the pack's base accent.
    #[arg(long, value_name = "ID")]
    pub accent: Option<String>,
    /// Print JSON (and nothing else) instead of a table.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct AssessArgs {
    #[command(flatten)]
    pub input: Input,
    /// Tone ids of the intended reading, one per syllable, e.g. "4 1 3".
    #[arg(long)]
    pub tones: String,
    /// One label per syllable, e.g. "yi bei shui"; shown in the table.
    #[arg(long)]
    pub labels: Option<String>,
    /// Another reading the speech might be mistaken for, e.g. "4 1 4". Repeatable; they get the
    /// candidate ids d1, d2, ... in order.
    #[arg(long = "distractor", value_name = "TONES")]
    pub distractors: Vec<String>,
    /// Also report how well the intended reading fits this accent. Repeatable.
    #[arg(long = "compare-accent", value_name = "ID")]
    pub compare_accents: Vec<String>,
}

#[derive(Debug, Args)]
pub struct LatticeArgs {
    #[command(flatten)]
    pub input: Input,
}
