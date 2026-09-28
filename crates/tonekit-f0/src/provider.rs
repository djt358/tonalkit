use tonekit_core::{F0Frame, F0Track};

/// A source of frame-level f0 estimates.
///
/// Implementations return exactly `pcm.len() / HOP + 1` frames for 16 kHz mono `pcm`, frame `i`
/// centred on sample `i * HOP`. A frame is voiced when `hz.is_some() && voiced_p >= 0.5`.
pub trait F0Provider {
    /// Short identifier stored in [`F0Track::provider`].
    fn name(&self) -> &str;
    /// Estimate f0 for every frame of `pcm`.
    fn track(&self, pcm: &[f32]) -> F0Track;
}

/// Bring `track` to exactly `frames` frames: truncate, or pad with unvoiced frames
/// (`hz = None`, `voiced_p = 0`). The provider name is kept.
///
/// Used for tracks that come from outside (a caller-supplied f0 track may be a frame or two
/// off the length the rest of the pipeline expects).
pub fn fit_length(mut track: F0Track, frames: usize) -> F0Track {
    track.frames.resize(
        frames,
        F0Frame {
            hz: None,
            voiced_p: 0.0,
        },
    );
    track
}
