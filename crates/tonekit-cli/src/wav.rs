//! Reading the WAV: 16 kHz mono, PCM16 or 32-bit float, nothing else.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

use hound::{SampleFormat, WavReader, WavSpec};
use tonekit::SAMPLE_RATE;

use crate::CliError;

/// Full scale of a PCM16 sample.
const PCM16_SCALE: f32 = 32_768.0;
/// How many RIFF chunks to skip looking for `fmt ` before giving up.
const MAX_CHUNKS: usize = 64;
/// `fmt ` chunk bytes worth reading: through the extensible sub-format tag.
const FMT_BYTES: usize = 26;

/// The samples of `path` as floats in `-1..1`.
///
/// A WAV in any other layout is a usage error (exit 2) whose message says how to convert it;
/// a file that cannot be read at all is a failure (exit 1).
pub fn read_mono_16k(path: &Path) -> Result<Vec<f32>, CliError> {
    let unreadable = |e: hound::Error| CliError::Failure(format!("{}: {e}", path.display()));
    let mut reader = match WavReader::open(path) {
        Ok(reader) => reader,
        // hound refuses some layouts outright (64-bit float, mu-law, ADPCM, ...). If the header
        // says the file is a WAV in a layout we do not take, that is a usage error like any
        // other wrong layout; anything else that will not open is just unreadable.
        Err(e) => {
            return Err(match sniff_layout(path).filter(|l| !l.is_supported()) {
                Some(layout) => wrong_layout(path, &layout),
                None => unreadable(e),
            })
        }
    };
    let layout = Layout::from(reader.spec());
    if !layout.is_supported() {
        return Err(wrong_layout(path, &layout));
    }
    match layout.kind {
        Kind::Float => reader.samples::<f32>().collect::<Result<_, _>>(),
        _ => reader
            .samples::<i16>()
            .map(|s| s.map(|x| f32::from(x) / PCM16_SCALE))
            .collect::<Result<_, _>>(),
    }
    .map_err(unreadable)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Kind {
    Pcm,
    Float,
    /// Any other WAVE format tag (mu-law, A-law, ADPCM, ...).
    Other(u16),
}

/// What a WAV's header says its samples are.
#[derive(Clone, Copy, Debug)]
struct Layout {
    rate: u32,
    channels: u16,
    bits: u16,
    kind: Kind,
}

impl Layout {
    fn is_supported(&self) -> bool {
        self.channels == 1
            && self.rate == SAMPLE_RATE
            && matches!((self.kind, self.bits), (Kind::Pcm, 16) | (Kind::Float, 32))
    }

    fn describe(&self) -> String {
        let kind = match self.kind {
            Kind::Pcm => "PCM".to_owned(),
            Kind::Float => "float".to_owned(),
            Kind::Other(2) => "ADPCM".to_owned(),
            Kind::Other(6) => "A-law".to_owned(),
            Kind::Other(7) => "mu-law".to_owned(),
            Kind::Other(tag) => format!("format {tag:#06x}"),
        };
        format!(
            "{} Hz, {} channel(s), {}-bit {kind}",
            self.rate, self.channels, self.bits
        )
    }
}

impl From<WavSpec> for Layout {
    fn from(spec: WavSpec) -> Self {
        Self {
            rate: spec.sample_rate,
            channels: spec.channels,
            bits: spec.bits_per_sample,
            kind: match spec.sample_format {
                SampleFormat::Int => Kind::Pcm,
                SampleFormat::Float => Kind::Float,
            },
        }
    }
}

fn wrong_layout(path: &Path, layout: &Layout) -> CliError {
    CliError::Usage(format!(
        "{}: expected a 16 kHz mono WAV of 16-bit PCM or 32-bit float, got {}; \
         resample with `tkh ingest`",
        path.display(),
        layout.describe()
    ))
}

/// The layout named by the `fmt ` chunk of a RIFF/WAVE file, read without decoding anything
/// else; `None` if `path` is not a RIFF/WAVE file or has no readable `fmt ` chunk.
fn sniff_layout(path: &Path) -> Option<Layout> {
    let mut file = File::open(path).ok()?;
    let mut riff = [0_u8; 12];
    file.read_exact(&mut riff).ok()?;
    if &riff[..4] != b"RIFF" || &riff[8..] != b"WAVE" {
        return None;
    }
    for _ in 0..MAX_CHUNKS {
        let mut head = [0_u8; 8];
        file.read_exact(&mut head).ok()?;
        let size = u32::from_le_bytes([head[4], head[5], head[6], head[7]]);
        if &head[..4] == b"fmt " {
            let mut body = vec![0_u8; usize::try_from(size).ok()?.min(FMT_BYTES)];
            file.read_exact(&mut body).ok()?;
            return layout_of_fmt(&body);
        }
        // Chunk bodies are padded to an even length.
        let skip = i64::from(size) + i64::from(size & 1);
        file.seek(SeekFrom::Current(skip)).ok()?;
    }
    None
}

/// Layout from the leading bytes of a `fmt ` chunk (WAVEFORMATEX, or the extensible variant
/// whose real format tag is the first two bytes of its sub-format GUID).
fn layout_of_fmt(fmt: &[u8]) -> Option<Layout> {
    let u16_at = |at: usize| {
        fmt.get(at..at + 2)
            .map(|b| u16::from_le_bytes([b[0], b[1]]))
    };
    let mut tag = u16_at(0)?;
    if tag == 0xFFFE {
        tag = u16_at(24)?;
    }
    Some(Layout {
        channels: u16_at(2)?,
        rate: u32::from(u16_at(4)?) | (u32::from(u16_at(6)?) << 16),
        bits: u16_at(14)?,
        kind: match tag {
            1 => Kind::Pcm,
            3 => Kind::Float,
            other => Kind::Other(other),
        },
    })
}
