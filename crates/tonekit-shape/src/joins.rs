//! Coarticulated edges (ruling R61): where one syllable runs straight into the next, the frames
//! nearest the join belong to the pitch's transition between the two tones, not to either tone.

use tonekit_core::TbuSpan;

/// Frames dropped from the voiced part at a coarticulated edge (30 ms): the half of a quick
/// tone-to-tone transition that falls on this side of the join.
pub const JOIN_TRIM_FRAMES: u32 = 3;

/// Which edges of a TBU are coarticulated joins with a neighbouring syllable (no pause between
/// them), as opposed to pauses or the ends of the speech.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Joins {
    pub start: bool,
    pub end: bool,
}

impl Joins {
    /// Neither edge is a join: the voiced part is measured to the span's edges.
    pub const NONE: Joins = Joins {
        start: false,
        end: false,
    };
}

/// The stretch of `span` a tone is measured on: `span` less [`JOIN_TRIM_FRAMES`] at each join
/// edge, and never more than a quarter of the span at either end.
pub(crate) fn measured_span(span: &TbuSpan, joins: Joins) -> TbuSpan {
    let len = span.end_frame.saturating_sub(span.start_frame);
    let trim = JOIN_TRIM_FRAMES.min(len / 4);
    TbuSpan {
        start_frame: span.start_frame + if joins.start { trim } else { 0 },
        end_frame: span.end_frame - if joins.end { trim } else { 0 },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn span(start_frame: u32, end_frame: u32) -> TbuSpan {
        TbuSpan {
            start_frame,
            end_frame,
        }
    }

    #[test]
    fn joins_lose_three_frames_and_pauses_none() {
        let both = Joins {
            start: true,
            end: true,
        };
        assert_eq!(measured_span(&span(40, 60), both), span(43, 57));
        assert_eq!(measured_span(&span(40, 60), Joins::NONE), span(40, 60));
        let end_only = Joins {
            start: false,
            end: true,
        };
        assert_eq!(measured_span(&span(40, 60), end_only), span(40, 57));
    }

    #[test]
    fn a_short_span_loses_at_most_a_quarter_at_each_join() {
        let both = Joins {
            start: true,
            end: true,
        };
        assert_eq!(measured_span(&span(40, 50), both), span(42, 48));
        assert_eq!(measured_span(&span(40, 43), both), span(40, 43));
        assert_eq!(measured_span(&span(40, 40), both), span(40, 40));
    }
}
