//! Closed-set decoding of one candidate (spec §7.2): a segmental DP over the boundary candidates.
//!
//! A path consumes the candidate's K targets in order. Between boundaries it takes either a
//! *syllable* edge, scored by the target's LLR against the background plus a log-duration prior,
//! or a *gap* edge, which charges every speech frame it covers as filler (silent frames are free).
//! Speech before the first and after the last syllable is filler too, so hesitations, restarts and
//! extra words cost a little per frame instead of shifting the targets onto the wrong syllables.
//! Because every syllable's evidence is relative to a background, candidates of different lengths
//! compete on one scale.

use tonekit_core::{
    Analysis, AssessError, Candidate, CandidateScore, EnergyTrack, GradingTarget, MeasureIssue,
    SyllableFit, TbuSpan, ToneTarget,
};
use tonekit_pack::{LanguagePack, TargetContext};
use tonekit_segment::{speech_threshold, SegmentParams};

use crate::cache::{unmeasured, Scorer, TargetKey};
use crate::duration::{log_prior, rate_s, FRAME_S};
use crate::{clamp_log, count_u32};

/// Shortest syllable edge, in frames (60 ms).
pub(crate) const MIN_SYLLABLE_FRAMES: u32 = 6;
/// Longest syllable edge, in frames (800 ms).
pub(crate) const MAX_SYLLABLE_FRAMES: u32 = 80;

/// Which frames are speech: finite energy at or above the speech threshold of the default
/// segmentation parameters (the ones the analysis was segmented with).
pub(crate) fn speech_mask(e: &EnergyTrack) -> Vec<bool> {
    let threshold = speech_threshold(e, &SegmentParams::default());
    e.db.iter()
        .map(|&d| d.is_finite() && d >= threshold)
        .collect()
}

/// Filler cost of frame spans: `per_frame` for every speech frame, nothing for silence.
pub(crate) struct Filler {
    /// `prefix[f]` = speech frames in `[0, f)`; one longer than the track.
    prefix: Vec<u32>,
    per_frame: f64,
}

impl Filler {
    pub(crate) fn new(speech: &[bool], per_frame: f64) -> Filler {
        let mut prefix = Vec::with_capacity(speech.len() + 1);
        let mut n = 0u32;
        prefix.push(0);
        for &s in speech {
            n += u32::from(s);
            prefix.push(n);
        }
        Filler { prefix, per_frame }
    }

    /// Frames in the track.
    pub(crate) fn frames(&self) -> u32 {
        count_u32(self.prefix.len() - 1)
    }

    /// The cost of frames `[from, to)`, clamped to the track (frames past it are silent).
    pub(crate) fn cost(&self, from: u32, to: u32) -> f64 {
        let last = self.prefix.len() - 1;
        let at = |f: u32| self.prefix[(f as usize).min(last)];
        let speech = at(to).saturating_sub(at(from));
        self.per_frame * f64::from(speech)
    }
}

/// The best path through the boundary candidates.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Path {
    pub score: f64,
    /// The boundary-index pair `(i, j)` of each syllable, in order.
    pub syllables: Vec<(usize, usize)>,
}

#[derive(Clone, Copy)]
enum Step {
    Start,
    Gap,
    Syllable { from: usize },
}

/// The best path placing `k` syllables on `bounds` (sorted, unique frames), or `None` if no path
/// places all of them.
///
/// `best[s][i]` is the best score of a path that has placed `s` syllables and stands at boundary
/// `i`:
/// - start: `best[0][i] = −cost(0, B_i)` for every `i` (leading speech is filler);
/// - gap edge `i → i+1`: `best[s][i+1] ≥ best[s][i] − cost(B_i, B_{i+1})`;
/// - syllable edge `i → j` for every `j > i` whose span is 60–800 ms:
///   `best[s+1][j] ≥ best[s][i] + syllable(i, j, s)`;
/// - end: `max_i best[k][i] − cost(B_i, end of track)` (trailing speech is filler).
///
/// `syllable(i, j, s)` scores target `s` on the span between boundaries `i` and `j`; it is only
/// called for reachable `(s, i)`. Ties keep the first path found (earlier boundaries, gap before
/// syllable edges, shorter syllable edges first).
pub(crate) fn best_path<E>(
    bounds: &[u32],
    filler: &Filler,
    k: usize,
    mut syllable: impl FnMut(usize, usize, usize) -> Result<f64, E>,
) -> Result<Option<Path>, E> {
    let n = bounds.len();
    let mut best = vec![vec![f64::NEG_INFINITY; n]; k + 1];
    let mut back = vec![vec![Step::Start; n]; k + 1];
    for (i, &b) in bounds.iter().enumerate() {
        best[0][i] = -filler.cost(0, b);
    }

    // Every edge moves to a later boundary, so boundary order is a topological order.
    for i in 0..n {
        for s in 0..=k {
            let here = best[s][i];
            if here == f64::NEG_INFINITY {
                continue;
            }
            if i + 1 < n {
                let v = here - filler.cost(bounds[i], bounds[i + 1]);
                if v > best[s][i + 1] {
                    best[s][i + 1] = v;
                    back[s][i + 1] = Step::Gap;
                }
            }
            if s == k {
                continue;
            }
            for j in i + 1..n {
                let frames = bounds[j] - bounds[i];
                if frames < MIN_SYLLABLE_FRAMES {
                    continue;
                }
                if frames > MAX_SYLLABLE_FRAMES {
                    break;
                }
                let v = here + syllable(i, j, s)?;
                if v > best[s + 1][j] {
                    best[s + 1][j] = v;
                    back[s + 1][j] = Step::Syllable { from: i };
                }
            }
        }
    }

    let mut end: Option<(f64, usize)> = None;
    for (i, &b) in bounds.iter().enumerate() {
        if best[k][i] == f64::NEG_INFINITY {
            continue;
        }
        let v = best[k][i] - filler.cost(b, filler.frames());
        if end.is_none_or(|(e, _)| v > e) {
            end = Some((v, i));
        }
    }
    let Some((score, mut i)) = end else {
        return Ok(None);
    };

    let mut s = k;
    let mut syllables = Vec::with_capacity(k);
    loop {
        match back[s][i] {
            Step::Start => break,
            Step::Gap => i -= 1,
            Step::Syllable { from } => {
                syllables.push((from, i));
                i = from;
                s -= 1;
            }
        }
    }
    syllables.reverse();
    Ok(Some(Path { score, syllables }))
}

/// The context of each of a candidate's targets: its index, the count, the previous *target*
/// tone, and whether it is the last.
pub(crate) fn contexts(targets: &[ToneTarget]) -> Vec<TargetContext> {
    let count = count_u32(targets.len());
    (0..targets.len())
        .map(|k| TargetContext {
            index: count_u32(k),
            count,
            prev: k.checked_sub(1).map(|p| targets[p].tone.clone()),
            phrase_final: k + 1 == targets.len(),
        })
        .collect()
}

/// Decodes candidates against one analysis, sharing the segment and LLR caches between them.
pub(crate) struct Decoder<'a> {
    /// Where the speech region starts, if there is one.
    speech_start: Option<u32>,
    /// The analysis's boundary candidates, sorted and unique.
    bounds: Vec<u32>,
    filler: Filler,
    /// The speaking rate `r` in seconds per syllable.
    rate_s: f64,
    dur_sigma: f64,
    scorer: Scorer<'a>,
}

impl<'a> Decoder<'a> {
    pub(crate) fn new(a: &'a Analysis, pack: &'a LanguagePack, g: &'a GradingTarget) -> Self {
        let d = &pack.calibration().decode;
        let mut bounds = a.boundaries.clone();
        bounds.sort_unstable();
        bounds.dedup();
        Decoder {
            speech_start: a.speech.as_ref().map(|r| r.start),
            bounds,
            filler: Filler::new(&speech_mask(&a.energy), f64::from(d.filler_per_frame)),
            rate_s: rate_s(&a.nuclei, f64::from(d.default_rate_s)),
            dur_sigma: f64::from(d.dur_sigma),
            scorer: Scorer::new(a, pack, g),
        }
    }

    /// The keys of the candidate's targets in their contexts, resolving (and so validating)
    /// everything [`Decoder::score`] will ask of the pack. Call it for every candidate before
    /// scoring any.
    pub(crate) fn plan(&mut self, cand: &Candidate) -> Result<Vec<TargetKey>, AssessError> {
        cand.targets
            .iter()
            .zip(contexts(&cand.targets))
            .map(|(t, c)| self.scorer.key(t, &c))
            .collect()
    }

    /// The candidate's best path, its LLR (the path score) and its syllables, each judged in its
    /// context; `keys` is its [`Decoder::plan`]. `posterior` is left at 0 for the caller to fill.
    pub(crate) fn score(
        &mut self,
        cand: &Candidate,
        keys: &[TargetKey],
    ) -> Result<CandidateScore, AssessError> {
        let path = match self.speech_start {
            Some(_) => {
                let (bounds, scorer) = (&self.bounds, &mut self.scorer);
                let (rate, sigma) = (self.rate_s, self.dur_sigma);
                best_path(bounds, &self.filler, keys.len(), |i, j, s| {
                    let (from, to) = (bounds[i], bounds[j]);
                    let d_s = f64::from(to - from) * FRAME_S;
                    let llr = scorer.llr(from, to, keys[s])?;
                    Ok(f64::from(llr) + log_prior(d_s, rate, sigma))
                })?
            }
            None => None,
        };
        let Some(path) = path else {
            return Ok(self.no_path(cand));
        };

        let ctxs = contexts(&cand.targets);
        let mut syllables = Vec::with_capacity(path.syllables.len());
        for ((&(i, j), target), ctx) in path.syllables.iter().zip(&cand.targets).zip(&ctxs) {
            let (from, to) = (self.bounds[i], self.bounds[j]);
            syllables.push(self.scorer.fit(from, to, target, ctx)?);
        }
        Ok(CandidateScore {
            id: cand.id.clone(),
            llr: clamp_log(path.score),
            posterior: 0.0,
            syllables,
        })
    }

    /// No speech region, or too few boundaries for every target: each syllable is unmeasured, at
    /// an empty span where the speech region starts (frame 0 without one), and the candidate
    /// scores `K × unvoiced_syllable_llr`.
    fn no_path(&self, cand: &Candidate) -> CandidateScore {
        let at = self.speech_start.unwrap_or(0);
        let unvoiced = self.scorer.unvoiced_llr();
        let syllables = cand
            .targets
            .iter()
            .map(|t| SyllableFit {
                span: TbuSpan {
                    start_frame: at,
                    end_frame: at,
                },
                judgement: unmeasured(t, MeasureIssue::Unvoiced, unvoiced),
            })
            .collect();
        CandidateScore {
            id: cand.id.clone(),
            llr: clamp_log(f64::from(cand.targets.len() as f32 * unvoiced)),
            posterior: 0.0,
            syllables,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::convert::Infallible;

    /// A filler of `frames` frames at 1.0 per speech frame, speech wherever `speech(f)` holds.
    fn filler(frames: usize, speech: impl Fn(usize) -> bool) -> Filler {
        let mask: Vec<bool> = (0..frames).map(speech).collect();
        Filler::new(&mask, 1.0)
    }

    fn path(
        bounds: &[u32],
        f: &Filler,
        k: usize,
        score: impl Fn(usize, usize, usize) -> f64,
    ) -> Option<Path> {
        best_path::<Infallible>(bounds, f, k, |i, j, s| Ok(score(i, j, s))).unwrap()
    }

    #[test]
    fn filler_counts_speech_frames_only_and_clamps_to_the_track() {
        let f = filler(10, |i| (2..6).contains(&i));
        assert_eq!(f.frames(), 10);
        assert_eq!(f.cost(0, 10), 4.0);
        assert_eq!(f.cost(3, 5), 2.0);
        assert_eq!(f.cost(6, 10), 0.0);
        assert_eq!(f.cost(0, 400), 4.0);
        assert_eq!(f.cost(5, 3), 0.0);
    }

    #[test]
    fn filler_absorbs_extra_speech_around_the_syllable() {
        // Speech everywhere; boundaries every 10 frames. Only 10 → 20 is a good syllable.
        let f = filler(40, |_| true);
        let bounds = [0, 10, 20, 30, 40];
        let p = path(
            &bounds,
            &f,
            1,
            |i, j, _| if (i, j) == (1, 2) { 50.0 } else { -50.0 },
        );
        let p = p.unwrap();
        assert_eq!(p.syllables, vec![(1, 2)]);
        // 10 leading and 20 trailing speech frames are charged as filler.
        assert_eq!(p.score, 50.0 - 30.0);
    }

    #[test]
    fn silent_frames_between_syllables_are_free() {
        // Two syllables separated by silence 20..30: the gap costs nothing.
        let f = filler(40, |i| !(20..30).contains(&i));
        let bounds = [0, 10, 20, 30, 40];
        let p = path(&bounds, &f, 2, |i, j, s| match (s, i, j) {
            (0, 1, 2) | (1, 3, 4) => 5.0,
            _ => -100.0,
        })
        .unwrap();
        assert_eq!(p.syllables, vec![(1, 2), (3, 4)]);
        assert_eq!(p.score, 10.0 - 10.0);
    }

    #[test]
    fn gap_edge_or_longer_syllable_whichever_scores_better() {
        // One target over speech 0..20: either the syllable 0 → 10 plus a gap edge charging the
        // 10 trailing speech frames (1 − 10 = −9), or one syllable over all of 0 → 20.
        let f = filler(20, |_| true);
        let bounds = [0, 10, 20];
        let score = |whole: f64| {
            move |i: usize, j: usize, _: usize| match (i, j) {
                (0, 1) => 1.0,
                (0, 2) => whole,
                _ => -100.0,
            }
        };
        let p = path(&bounds, &f, 1, score(-5.0)).unwrap();
        assert_eq!((p.syllables, p.score), (vec![(0, 2)], -5.0));
        let p = path(&bounds, &f, 1, score(-15.0)).unwrap();
        assert_eq!((p.syllables, p.score), (vec![(0, 1)], -9.0));
    }

    #[test]
    fn the_worst_span_is_the_one_left_as_filler() {
        // Two targets over three 10-frame spans of speech: one span has to be filler (cost 10).
        let f = filler(30, |_| true);
        let bounds = [0, 10, 20, 30];
        let spans = |a: f64, b: f64, c: f64| {
            move |i: usize, j: usize, _: usize| match (i, j) {
                (0, 1) => a,
                (1, 2) => b,
                (2, 3) => c,
                _ => -100.0,
            }
        };
        let p = path(&bounds, &f, 2, spans(1.0, -30.0, 2.0)).unwrap();
        assert_eq!((p.syllables, p.score), (vec![(0, 1), (2, 3)], 3.0 - 10.0));
        let p = path(&bounds, &f, 2, spans(-30.0, 1.0, 2.0)).unwrap();
        assert_eq!((p.syllables, p.score), (vec![(1, 2), (2, 3)], 3.0 - 10.0));
        // Three targets use every span, however poor.
        let p = path(&bounds, &f, 3, spans(1.0, -30.0, 2.0)).unwrap();
        assert_eq!(
            (p.syllables, p.score),
            (vec![(0, 1), (1, 2), (2, 3)], -27.0)
        );
    }

    #[test]
    fn syllable_edges_respect_the_duration_window() {
        let f = filler(200, |_| true);
        // Spans of 5 frames (50 ms) and 81 frames are out; 6 (60 ms) and 80 (800 ms) are in.
        let bounds = [0, 5, 6, 86, 87];
        let mut seen = Vec::new();
        let _ = best_path::<Infallible>(&bounds, &f, 1, |i, j, _| {
            seen.push((bounds[i], bounds[j]));
            Ok(0.0)
        });
        assert_eq!(seen, vec![(0, 6), (6, 86)]);
    }

    #[test]
    fn no_path_when_too_few_boundaries() {
        let f = filler(40, |_| true);
        // Three boundaries allow at most two syllables.
        assert!(path(&[0, 10, 20], &f, 3, |_, _, _| 0.0).is_none());
        assert!(path(&[0, 10, 20], &f, 2, |_, _, _| 0.0).is_some());
        // Spans shorter than 60 ms are never syllables.
        assert!(path(&[0, 3], &f, 1, |_, _, _| 0.0).is_none());
        assert!(path(&[], &f, 1, |_, _, _| 0.0).is_none());
    }

    #[test]
    fn scorer_errors_propagate() {
        let f = filler(40, |_| true);
        let r = best_path(&[0, 10, 20], &f, 1, |_, _, _| Err::<f64, _>("boom"));
        assert_eq!(r, Err("boom"));
    }

    #[test]
    fn contexts_carry_the_previous_target_tone() {
        use tonekit_core::ToneId;
        let t = |s: &str| ToneTarget {
            tone: ToneId(s.into()),
            lexical_variants: Vec::new(),
            label: None,
        };
        let ctx = contexts(&[t("3"), t("5"), t("4")]);
        assert_eq!(ctx.len(), 3);
        assert_eq!(ctx[0].prev, None);
        assert_eq!(ctx[1].prev, Some(ToneId("3".into())));
        assert_eq!(ctx[2].prev, Some(ToneId("5".into())));
        assert!(ctx.iter().all(|c| c.count == 3));
        assert_eq!(
            ctx.iter().map(|c| c.phrase_final).collect::<Vec<_>>(),
            [false, false, true]
        );
        assert_eq!(ctx.iter().map(|c| c.index).collect::<Vec<_>>(), [0, 1, 2]);
    }
}
