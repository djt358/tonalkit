use tonekit_core::{EnergyTrack, FrameRange};

use crate::smooth::frame;

/// A speech region needs at least this many frames above the threshold.
const MIN_SPEECH_FRAMES: usize = 5;
/// The quiet-level percentile of the frame energies.
const FLOOR_QUANTILE: f64 = 0.10;

/// Segmentation parameters (the seeds are the [`Default`]).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SegmentParams {
    /// How far above the quiet level (the 10th-percentile frame dB) a frame must be to count as
    /// speech. Default 10 dB.
    pub speech_margin_db: f32,
    /// Two energy peaks are one nucleus unless the valley between them is more than this far
    /// below the lower peak. Default 2 dB.
    pub dip_db: f32,
    /// Two energy peaks closer than this many frames are one nucleus. Default 6 frames (60 ms).
    pub min_nucleus_gap: u32,
}

impl Default for SegmentParams {
    fn default() -> Self {
        Self {
            speech_margin_db: 10.0,
            dip_db: 2.0,
            min_nucleus_gap: 6,
        }
    }
}

/// The quiet level of `e`: its 10th-percentile frame dB (linearly interpolated, like
/// `tonekit_f0::snr_db`), ignoring non-finite frames. `None` if no frame is finite.
pub(crate) fn floor_db(e: &EnergyTrack) -> Option<f32> {
    let mut db: Vec<f32> = e.db.iter().copied().filter(|d| d.is_finite()).collect();
    if db.is_empty() {
        return None;
    }
    db.sort_by(f32::total_cmp);
    let rank = FLOOR_QUANTILE * (db.len() - 1) as f64;
    let below = rank.floor() as usize;
    let above = (below + 1).min(db.len() - 1);
    let (lo, hi) = (f64::from(db[below]), f64::from(db[above]));
    Some((lo + (rank - below as f64) * (hi - lo)) as f32)
}

/// The frame energy a frame must exceed to count as speech: the 10th-percentile frame dB plus
/// `p.speech_margin_db`.
///
/// A track with no finite frame has no quiet level; its threshold is `+inf`, so nothing in it is
/// speech.
pub fn speech_threshold(e: &EnergyTrack, p: &SegmentParams) -> f32 {
    floor_db(e).map_or(f32::INFINITY, |floor| floor + p.speech_margin_db)
}

/// Which frames of `e` are speech: finite and strictly above [`speech_threshold`]. The one test
/// for speech, shared by the speech region, the pause edges among the boundaries and the
/// decoder's filler.
pub fn speech_frames(e: &EnergyTrack, p: &SegmentParams) -> Vec<bool> {
    let threshold = speech_threshold(e, p);
    e.db.iter()
        .map(|&d| d.is_finite() && d > threshold)
        .collect()
}

/// The stretch of `e` that holds speech: from the first to the last [speech frame](speech_frames),
/// half-open (`end` is one past the last such frame).
///
/// Pauses between syllables stay inside the region. `None` if fewer than 5 frames are speech
/// (silence, a click, or a constant hum).
pub fn speech_region(e: &EnergyTrack, p: &SegmentParams) -> Option<FrameRange> {
    let loud: Vec<usize> = speech_frames(e, p)
        .into_iter()
        .enumerate()
        .filter_map(|(i, speech)| speech.then_some(i))
        .collect();
    let (&first, &last) = (loud.first()?, loud.last()?);
    (loud.len() >= MIN_SPEECH_FRAMES).then(|| FrameRange {
        start: frame(first),
        end: frame(last + 1),
    })
}
