//! Per-nucleus tone evidence (ruling R50), shared by the closed-set DP, the null competitor and the
//! open lattice.
//!
//! Each nucleus's shape is extracted once, on its tone-bearing unit (TBU): the span between the
//! nearest boundary candidates on either side of it, with the voiced part restricted to the
//! nucleus's own voiced run ([`tonekit_shape::extract_nucleus`]), less the frames beside an edge
//! where it runs straight into a neighbouring syllable (ruling R61). Every candidate that puts a
//! syllable on a nucleus is scored on that one shape, so no reading can choose the frames that
//! suit it best, and the closed-set decode and the lattice see the same evidence.

use tonekit_core::{Analysis, EnergyTrack, MeasureIssue, TbuSpan};
use tonekit_segment::{speech_frames, SegmentParams};
use tonekit_shape::{extract_nucleus, Extracted, Joins, JOIN_TRIM_FRAMES};

use crate::count_u32;

/// A TBU's shape, or why there is none.
pub(crate) type Segment = Result<Extracted, MeasureIssue>;

/// One nucleus's tone evidence.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Tbu {
    pub span: TbuSpan,
    pub segment: Segment,
}

/// The evidence of every distinct nucleus of `a`, in frame order: its TBU ([`tbu_spans`], falling
/// back to the speech region's edges, or the track's without one) and the shape of its own voiced
/// run there, normalised by the analysis's register, with the frames beside a coarticulated edge
/// left out ([`joins`], ruling R61).
pub(crate) fn tbus(a: &Analysis) -> Vec<Tbu> {
    let voice_level = voice_level_frames(&a.energy);
    let pitched: Vec<bool> = a.f0.frames.iter().map(|f| f.hz.is_some()).collect();
    let mut nuclei: Vec<u32> = a.nuclei.iter().map(|n| n.frame).collect();
    nuclei.sort_unstable();
    nuclei.dedup();
    let (lo_edge, hi_edge) = match &a.speech {
        Some(r) => (r.start, r.end),
        None => (0, count_u32(a.f0.frames.len())),
    };
    tbu_spans(&nuclei, &a.boundaries, lo_edge, hi_edge)
        .into_iter()
        .zip(nuclei)
        .map(|(span, nucleus)| Tbu {
            segment: extract_nucleus(
                &a.f0,
                &span,
                nucleus,
                &a.register,
                joins(&voice_level, &pitched, &span),
            ),
            span,
        })
        .collect()
}

/// Which frames are loud enough to be a voice rather than the room (ruling R61): above the quiet
/// level by half the speech margin. A dip between two syllables can fall below the speech
/// threshold in a noisy room and still be voice; silence and room noise cannot rise above this.
fn voice_level_frames(e: &EnergyTrack) -> Vec<bool> {
    let p = SegmentParams::default();
    speech_frames(
        e,
        &SegmentParams {
            speech_margin_db: p.speech_margin_db / 2.0,
            ..p
        },
    )
}

/// Which edges of `span` are coarticulated joins (ruling R61): the voice runs from one syllable
/// straight into the next, so every frame within [`JOIN_TRIM_FRAMES`] on either side of the edge
/// is at voice level (`voice_level[i]`) and the frames either side of it both have a pitch
/// (`pitched[i]`). A pause, a consonant's silence or noise, a pitch break, the speech region's own
/// edges and the ends of the track are not joins.
fn joins(voice_level: &[bool], pitched: &[bool], span: &TbuSpan) -> Joins {
    let reach = JOIN_TRIM_FRAMES as usize;
    let join = |edge: u32| {
        let edge = edge as usize;
        edge >= reach
            && edge + reach <= voice_level.len()
            && voice_level[edge - reach..edge + reach].iter().all(|&v| v)
            && pitched
                .get(edge - 1..=edge)
                .is_some_and(|p| p.iter().all(|&v| v))
    };
    Joins {
        start: join(span.start_frame),
        end: join(span.end_frame),
    }
}

/// The TBU of each nucleus: from the nearest boundary strictly before the nucleus frame to the
/// nearest boundary strictly after it.
///
/// - With no boundary before (after) the nucleus, the TBU starts (ends) at `lo_edge` (`hi_edge`),
///   widened if need be so the nucleus frame stays inside.
/// - Neighbouring TBUs that would overlap — nuclei sharing both bounds, or a nucleus sitting on a
///   boundary — are cut at the frame midway between their nuclei (rounded up, so each nucleus
///   stays inside its own TBU).
///
/// `nuclei` and `bounds` are frame positions in any order; the TBUs follow the nuclei in time, one
/// per distinct nucleus frame, and never overlap.
fn tbu_spans(nuclei: &[u32], bounds: &[u32], lo_edge: u32, hi_edge: u32) -> Vec<TbuSpan> {
    let mut frames = nuclei.to_vec();
    frames.sort_unstable();
    frames.dedup();
    let mut spans: Vec<TbuSpan> = frames
        .iter()
        .map(|&f| TbuSpan {
            start_frame: bounds
                .iter()
                .copied()
                .filter(|&b| b < f)
                .max()
                .unwrap_or(lo_edge.min(f)),
            end_frame: bounds
                .iter()
                .copied()
                .filter(|&b| b > f)
                .min()
                .unwrap_or(hi_edge.max(f.saturating_add(1))),
        })
        .collect();
    for q in 1..spans.len() {
        if spans[q - 1].end_frame > spans[q].start_frame {
            let (left, right) = (frames[q - 1], frames[q]);
            let cut = left + (right - left).div_ceil(2);
            spans[q - 1].end_frame = cut;
            spans[q].start_frame = cut;
        }
    }
    spans
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::hand;
    use tonekit_core::{FrameRange, Nucleus};

    fn span(start_frame: u32, end_frame: u32) -> TbuSpan {
        TbuSpan {
            start_frame,
            end_frame,
        }
    }

    #[test]
    fn an_edge_is_a_join_only_with_voice_all_around_it_and_pitch_on_both_sides() {
        // Voice on 10..40 and 42..70 (a two-frame pause at 40..42): 30 is inside the first stretch,
        // 40 and 44 are within three frames of the pause, and 10 and 70 are the ends of the voice.
        let speech: Vec<bool> = (0..80)
            .map(|i| (10..40).contains(&i) || (42..70).contains(&i))
            .collect();
        let pitched = vec![true; 80];
        let edges = |start, end| joins(&speech, &pitched, &span(start, end));
        let both = Joins {
            start: true,
            end: true,
        };
        assert_eq!(edges(20, 30), both);
        assert_eq!(
            edges(30, 40),
            Joins {
                start: true,
                end: false
            }
        );
        assert_eq!(
            edges(10, 30),
            Joins {
                start: false,
                end: true
            }
        );
        assert_eq!(edges(44, 70), Joins::NONE);
        assert_eq!(edges(13, 37), both);
        assert_eq!(
            edges(12, 38),
            Joins {
                start: false,
                end: false
            }
        );
        // A pitch break at the edge (frame 29 or 30 unvoiced) is not a join either.
        let mut broken = vec![true; 80];
        broken[30] = false;
        assert!(!joins(&speech, &broken, &span(20, 30)).end);
        assert!(joins(&speech, &broken, &span(20, 32)).end);
        broken[30] = true;
        broken[29] = false;
        assert!(!joins(&speech, &broken, &span(30, 40)).start);
        // The ends of the track are never joins.
        assert_eq!(joins(&[true; 5], &[true; 5], &span(1, 4)), Joins::NONE);
    }

    #[test]
    fn tbus_take_the_nearest_boundaries_on_either_side() {
        let bounds = [20, 23, 33, 45, 48, 51, 76, 82, 108];
        assert_eq!(
            tbu_spans(&[31, 65, 102], &bounds, 20, 108),
            vec![span(23, 33), span(51, 76), span(82, 108)]
        );
        // A nucleus on a boundary is bounded by the ones strictly before and after it.
        assert_eq!(tbu_spans(&[48], &bounds, 20, 108), vec![span(45, 51)]);
    }

    #[test]
    fn tbus_fall_back_to_the_region_edges() {
        assert_eq!(tbu_spans(&[30], &[40, 60], 10, 90), vec![span(10, 40)]);
        assert_eq!(tbu_spans(&[70], &[40, 60], 10, 90), vec![span(60, 90)]);
        assert_eq!(tbu_spans(&[70], &[], 10, 90), vec![span(10, 90)]);
        // The fallback never leaves the nucleus outside its TBU.
        assert_eq!(tbu_spans(&[5], &[], 10, 90), vec![span(5, 90)]);
    }

    #[test]
    fn nuclei_sharing_both_bounds_split_midway() {
        // 30 and 50 both sit between boundaries 20 and 70: split at 40.
        assert_eq!(
            tbu_spans(&[50, 30], &[20, 70], 0, 100),
            vec![span(20, 40), span(40, 70)]
        );
        // Three in one gap: cuts at 35 and 55.
        assert_eq!(
            tbu_spans(&[30, 40, 70], &[20, 80], 0, 100),
            vec![span(20, 35), span(35, 55), span(55, 80)]
        );
        // Only the run that shares bounds is split.
        assert_eq!(
            tbu_spans(&[10, 30, 50], &[20, 70], 0, 100),
            vec![span(0, 20), span(20, 40), span(40, 70)]
        );
    }

    #[test]
    fn tbus_never_overlap_when_a_nucleus_sits_on_a_boundary() {
        // 40 is both a nucleus and a boundary: its TBU is (20, 60), and 50's is (40, 60).
        assert_eq!(
            tbu_spans(&[40, 50], &[20, 40, 60], 0, 100),
            vec![span(20, 45), span(45, 60)]
        );
        // A nucleus on a boundary right after its neighbour's nucleus.
        assert_eq!(
            tbu_spans(&[30, 40], &[20, 40, 60], 0, 100),
            vec![span(20, 35), span(35, 60)]
        );
    }

    #[test]
    fn every_nucleus_stays_inside_its_own_tbu() {
        // Odd and unit spacings round the cut up; a repeated nucleus is one TBU.
        assert_eq!(
            tbu_spans(&[30, 45], &[20, 70], 0, 100),
            vec![span(20, 38), span(38, 70)]
        );
        assert_eq!(
            tbu_spans(&[30, 31], &[20, 70], 0, 100),
            vec![span(20, 31), span(31, 70)]
        );
        assert_eq!(tbu_spans(&[30, 30], &[20, 70], 0, 100), vec![span(20, 70)]);
        for (nuclei, bounds) in [
            (vec![5, 12, 13, 40, 41, 90], vec![10, 13, 40, 60]),
            (vec![0, 1, 2], vec![]),
            (vec![50, 20, 80], vec![20, 50, 80]),
        ] {
            let spans = tbu_spans(&nuclei, &bounds, 0, 100);
            let mut sorted = nuclei.clone();
            sorted.sort_unstable();
            sorted.dedup();
            assert_eq!(spans.len(), sorted.len());
            for (s, &f) in spans.iter().zip(&sorted) {
                assert!(s.start_frame <= f && f < s.end_frame, "{f} in {s:?}");
            }
            for pair in spans.windows(2) {
                assert!(pair[0].end_frame <= pair[1].start_frame, "{spans:?}");
            }
        }
    }

    #[test]
    fn each_nucleus_is_measured_on_its_own_run_inside_its_tbu() {
        // Level syllables at Chao 2 (frames 10..35) and Chao 5 (41..66), and no boundary in the
        // pause: the first TBU runs to frame 45 and so holds the second syllable's first four
        // frames, which are not its evidence.
        let mut a = hand(&[&[2.0], &[5.0]]);
        a.nuclei = [22, 53, 22]
            .map(|frame| Nucleus {
                frame,
                strength_db: 20.0,
            })
            .to_vec();
        a.boundaries = vec![10, 45, 72];
        a.speech = Some(FrameRange { start: 10, end: 72 });
        let found = tbus(&a);
        assert_eq!(found.len(), 2);
        let want = [(span(10, 45), 2.0), (span(45, 72), 5.0)];
        for (tbu, (want_span, level)) in found.iter().zip(want) {
            assert_eq!(tbu.span, want_span);
            let ex = tbu.segment.as_ref().unwrap();
            assert_eq!(ex.shape.span, want_span);
            assert!(
                ex.shape.contour.iter().all(|c| (c - level).abs() < 0.01),
                "{tbu:?}"
            );
        }
        // Without a speech region the TBUs fall back to the track's edges.
        a.boundaries.clear();
        a.speech = None;
        let spans: Vec<TbuSpan> = tbus(&a).into_iter().map(|t| t.span).collect();
        assert_eq!(spans, [span(0, 38), span(38, 72)]);
    }
}
