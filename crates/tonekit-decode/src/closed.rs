//! Closed-set decoding of one candidate (spec §7.2): a segmental DP over the boundary candidates.
//!
//! A path consumes the candidate's K targets in order. Between boundaries it takes either a
//! *syllable* edge, scored by the target's LLR against the background plus a log-duration prior,
//! or a *gap* edge, which charges every speech frame it covers as filler (silent frames are free)
//! and every nucleus it covers as an inserted syllable (`insertion_llr`, ruling R33). Speech before
//! the first and after the last syllable is charged the same way, so hesitations, restarts and
//! extra words cost a fixed amount per syllable plus a little per frame instead of shifting the
//! targets onto the wrong syllables. Because every syllable's evidence is relative to a
//! background, candidates of different lengths compete on one scale.
//!
//! Syllables are anchored on nuclei (ruling R33). The strict pass puts exactly one nucleus in
//! every syllable, so a target can neither hide on a sliver of a syllable nor straddle two. Only
//! when no strict path exists (fewer nuclei than targets, or boundaries that do not allow it) and
//! the analysis has a nucleus, the count stage (ruling R102) adds the extra syllable candidates as
//! anchors; failing that too, a relaxed pass allows syllables with no anchor: each is a likely
//! miss, scored `unvoiced_syllable_llr` and reported `Partial { [NoNucleus] }`.
//!
//! A syllable's tone evidence is its nucleus's shape, the same for every edge that holds the
//! nucleus and for every candidate (ruling R50): the boundary pair only sets the duration prior and
//! what is left over as filler and insertions, so a target cannot choose the frames that suit it.

use tonekit_core::{
    Analysis, AssessError, Candidate, CandidateScore, EnergyTrack, GradingTarget, MeasureIssue,
    SyllableFit, TbuSpan, ToneTarget,
};
use tonekit_pack::{LanguagePack, TargetContext};
use tonekit_segment::{speech_frames, SegmentParams};

use crate::cache::{missed, unmeasured, Scorer, TargetKey};
use crate::duration::{log_prior, rate_s, FRAME_S};
use crate::evidence::{Extended, Tbu};
use crate::{clamp_log, count_u32};

/// Shortest syllable edge, in frames (60 ms).
pub(crate) const MIN_SYLLABLE_FRAMES: u32 = 6;
/// Longest syllable edge, in frames (800 ms).
pub(crate) const MAX_SYLLABLE_FRAMES: u32 = 80;

/// Which frames are speech under the default segmentation parameters (the ones the analysis was
/// segmented with): the same test as the speech region and the pause edges.
pub(crate) fn speech_mask(e: &EnergyTrack) -> Vec<bool> {
    speech_frames(e, &SegmentParams::default())
}

/// Running counts over the track: `prefix[f]` = marked frames in `[0, f)`, one longer than the
/// track.
fn prefix_counts(marked: impl Iterator<Item = bool>) -> Vec<u32> {
    let mut prefix = vec![0u32];
    let mut n = 0u32;
    for m in marked {
        n += u32::from(m);
        prefix.push(n);
    }
    prefix
}

/// What frames cost when no syllable covers them: `per_frame` for every speech frame (silence is
/// free) and `−insertion_llr` for every nucleus, an inserted syllable (ruling R33). Also counts
/// the anchors in a span (the nuclei, and in the count stage the extra candidates too, ruling
/// R102), for the anchor rule on syllable edges.
pub(crate) struct Filler {
    /// Prefix counts of speech frames.
    speech: Vec<u32>,
    /// Prefix counts of anchor frames (each distinct frame once).
    nuclei: Vec<u32>,
    /// Prefix counts of the frames an uncovered anchor costs an insertion at: the nuclei.
    inserted: Vec<u32>,
    per_frame: f64,
    insertion_llr: f64,
}

/// `marked[f]` for every frame of `frames` on a track of `len` frames (repeats count once, frames
/// past the track are ignored).
fn marks(len: usize, frames: &[u32]) -> Vec<bool> {
    let mut marked = vec![false; len];
    for &f in frames {
        if let Some(slot) = marked.get_mut(f as usize) {
            *slot = true;
        }
    }
    marked
}

impl Filler {
    /// `speech` marks the speech frames; `nuclei` are nucleus frames in any order (repeats count
    /// once, frames past the track are ignored), each an anchor that costs an insertion when no
    /// syllable covers it.
    #[cfg(test)]
    pub(crate) fn new(speech: &[bool], nuclei: &[u32], per_frame: f64, insertion_llr: f64) -> Self {
        Self::with_anchors(speech, nuclei, nuclei, per_frame, insertion_llr)
    }

    /// As [`Filler::new`], with `anchors` for the anchor rule and only those of `inserted` costing
    /// an insertion when left uncovered (ruling R102: an extra candidate the reading does not use
    /// is no inserted syllable, only its speech frames are filler).
    pub(crate) fn with_anchors(
        speech: &[bool],
        anchors: &[u32],
        inserted: &[u32],
        per_frame: f64,
        insertion_llr: f64,
    ) -> Self {
        Filler {
            speech: prefix_counts(speech.iter().copied()),
            nuclei: prefix_counts(marks(speech.len(), anchors).into_iter()),
            inserted: prefix_counts(marks(speech.len(), inserted).into_iter()),
            per_frame,
            insertion_llr,
        }
    }

    /// Frames in the track.
    pub(crate) fn frames(&self) -> u32 {
        count_u32(self.speech.len() - 1)
    }

    /// Marked frames of `prefix` in `[from, to)`, clamped to the track.
    fn count(prefix: &[u32], from: u32, to: u32) -> u32 {
        let last = prefix.len() - 1;
        let at = |f: u32| prefix[(f as usize).min(last)];
        at(to).saturating_sub(at(from))
    }

    /// Nuclei in frames `[from, to)`.
    pub(crate) fn nuclei(&self, from: u32, to: u32) -> u32 {
        Self::count(&self.nuclei, from, to)
    }

    /// The first nucleus in frames `[from, to)`, if any, as its index among the distinct nucleus
    /// frames on the track in frame order (the order of [`crate::evidence::tbus`]).
    pub(crate) fn nucleus_in(&self, from: u32, to: u32) -> Option<usize> {
        (self.nuclei(from, to) > 0).then(|| Self::count(&self.nuclei, 0, from) as usize)
    }

    /// The cost of leaving frames `[from, to)` to no syllable, clamped to the track (frames past
    /// it are silent): `per_frame × speech frames − insertion_llr × nuclei`.
    pub(crate) fn cost(&self, from: u32, to: u32) -> f64 {
        let speech = Self::count(&self.speech, from, to);
        let inserted = Self::count(&self.inserted, from, to);
        self.per_frame * f64::from(speech) - self.insertion_llr * f64::from(inserted)
    }
}

/// Which syllable edges a DP pass may take (ruling R33).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Pass {
    /// Every syllable holds exactly one nucleus.
    Strict,
    /// Every syllable holds at most one nucleus.
    Relaxed,
}

impl Pass {
    /// The fewest nuclei a syllable edge of this pass holds.
    fn min_nuclei(self) -> u32 {
        match self {
            Pass::Strict => 1,
            Pass::Relaxed => 0,
        }
    }
}

/// At most this many nuclei in one syllable edge, in either pass.
const MAX_NUCLEI: u32 = 1;

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
/// - start: `best[0][i] = −cost(0, B_i)` for every `i` (leading speech and nuclei are filler
///   and insertions);
/// - gap edge `i → i+1`: `best[s][i+1] ≥ best[s][i] − cost(B_i, B_{i+1})`;
/// - syllable edge `i → j` for every `j > i` whose span is 60–800 ms and holds the nuclei `pass`
///   allows (exactly one when strict, at most one when relaxed):
///   `best[s+1][j] ≥ best[s][i] + syllable(i, j, s)`;
/// - end: `max_i best[k][i] − cost(B_i, end of track)` (trailing speech and nuclei likewise).
///
/// `syllable(i, j, s)` scores target `s` on the span between boundaries `i` and `j`; it is only
/// called for reachable `(s, i)` and allowed edges. Ties keep the first path found (earlier
/// boundaries, gap before syllable edges, shorter syllable edges first).
pub(crate) fn best_path<E>(
    bounds: &[u32],
    filler: &Filler,
    k: usize,
    pass: Pass,
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
                // Nuclei only accumulate as j grows.
                let nuclei = filler.nuclei(bounds[i], bounds[j]);
                if nuclei > MAX_NUCLEI {
                    break;
                }
                if nuclei < pass.min_nuclei() {
                    continue;
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

/// One segmentation the DP searches: its boundaries, filler, speaking rate and where its anchors'
/// evidence starts in the scorer's table.
struct Stage {
    /// Boundary candidates, sorted and unique.
    bounds: Vec<u32>,
    filler: Filler,
    /// The speaking rate `r` in seconds per syllable.
    rate_s: f64,
    /// The index of the stage's first anchor in the scorer's evidence table.
    offset: usize,
}

impl Stage {
    /// The stage over `anchors` (sorted, unique) and `bounds`, where only `inserted` cost an
    /// insertion when uncovered and the anchors' evidence starts at `offset`.
    fn new(
        a: &Analysis,
        pack: &LanguagePack,
        anchors: &[u32],
        inserted: &[u32],
        bounds: &[u32],
        offset: usize,
    ) -> Stage {
        let d = &pack.calibration().decode;
        let mut bounds = bounds.to_vec();
        bounds.sort_unstable();
        bounds.dedup();
        let filler = Filler::with_anchors(
            &speech_mask(&a.energy),
            anchors,
            inserted,
            f64::from(d.filler_per_frame),
            f64::from(d.insertion_llr),
        );
        Stage {
            bounds,
            filler,
            rate_s: rate_s(anchors, f64::from(d.default_rate_s)),
            offset,
        }
    }
}

/// Which stage a path was found in.
#[derive(Clone, Copy)]
enum Which {
    Nuclei,
    Count,
}

/// Decodes candidates against one analysis, sharing the nuclei's evidence and LLR caches between
/// them.
///
/// Two stages (ruling R102). The nuclei's: the analysis's nuclei and boundaries, as R33 and R50
/// define them. The count stage, for a candidate the nuclei cannot place: the nuclei and the extra
/// syllable candidates ([`crate::evidence::extended`]) together as anchors, over both sets of
/// boundaries, an uncovered candidate costing no insertion. The relaxed pass (syllables with no
/// anchor) runs in the count stage when there is one.
pub(crate) struct Decoder<'a> {
    /// Where the speech region starts, if there is one.
    speech_start: Option<u32>,
    nuclei: Stage,
    count: Option<Stage>,
    /// Whether the analysis has a nucleus on the track.
    has_nuclei: bool,
    dur_sigma: f64,
    scorer: Scorer<'a>,
}

impl<'a> Decoder<'a> {
    /// `tbus` is the evidence table: the nuclei's ([`crate::evidence::tbus`]) followed, when
    /// `extended` is given, by the count stage's (`extended.tbus`, one per anchor).
    pub(crate) fn new(
        a: &'a Analysis,
        pack: &'a LanguagePack,
        g: &'a GradingTarget,
        tbus: &'a [Tbu],
        extended: Option<&Extended>,
    ) -> Self {
        let mut nuclei: Vec<u32> = a.nuclei.iter().map(|n| n.frame).collect();
        nuclei.sort_unstable();
        nuclei.dedup();
        let first = Stage::new(a, pack, &nuclei, &nuclei, &a.boundaries, 0);
        let count = extended.map(|x| {
            let offset = tbus.len() - x.tbus.len();
            Stage::new(a, pack, &x.anchors, &nuclei, &x.bounds, offset)
        });
        Decoder {
            speech_start: a.speech.as_ref().map(|r| r.start),
            has_nuclei: first.filler.nuclei(0, first.filler.frames()) > 0,
            nuclei: first,
            count,
            dur_sigma: f64::from(pack.calibration().decode.dur_sigma),
            scorer: Scorer::new(a, pack, g, tbus),
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

    fn stage(&self, which: Which) -> &Stage {
        match (which, &self.count) {
            (Which::Count, Some(count)) => count,
            _ => &self.nuclei,
        }
    }

    /// The candidate's best path, its LLR (the path score) and its syllables, each judged in its
    /// context; `keys` is its [`Decoder::plan`]. `posterior` is left at 0 for the caller to fill.
    ///
    /// A syllable with an anchor is judged on the anchor's evidence and reported at the anchor's
    /// TBU, where that evidence was measured (the lattice's span for a nucleus, whatever boundary
    /// pair the path took); one without (relaxed pass only) is a likely miss at its path's span,
    /// clipped to the gap its neighbours' spans leave ([`clip_unanchored`]):
    /// `unvoiced_syllable_llr`, `Partial { [NoNucleus] }`.
    pub(crate) fn score(
        &mut self,
        cand: &Candidate,
        keys: &[TargetKey],
    ) -> Result<CandidateScore, AssessError> {
        let Some((path, which)) = self.search(keys)? else {
            return Ok(self.no_path(cand));
        };

        let ctxs = contexts(&cand.targets);
        let unvoiced = self.scorer.unvoiced_llr();
        let mut syllables = Vec::with_capacity(path.syllables.len());
        let mut anchored = Vec::with_capacity(path.syllables.len());
        for ((&(i, j), target), ctx) in path.syllables.iter().zip(&cand.targets).zip(&ctxs) {
            let stage = self.stage(which);
            let (from, to) = (stage.bounds[i], stage.bounds[j]);
            let anchor = stage.filler.nucleus_in(from, to).map(|n| stage.offset + n);
            anchored.push(anchor.is_some());
            let fit = match anchor {
                Some(n) => self.scorer.fit(n, target, ctx)?,
                None => SyllableFit {
                    span: TbuSpan {
                        start_frame: from,
                        end_frame: to,
                    },
                    judgement: missed(target, unvoiced),
                },
            };
            syllables.push(fit);
        }
        clip_unanchored(&mut syllables, &anchored);
        Ok(CandidateScore {
            id: cand.id.clone(),
            llr: clamp_log(path.score),
            posterior: 0.0,
            syllables,
        })
    }

    /// The best strict path in the nuclei's stage; failing that, the best strict one in the count
    /// stage (ruling R102); failing that, the best relaxed one in the count stage (the nuclei's
    /// without one). `None` without a speech region or a nucleus (no syllable can be anchored), or
    /// when no pass places every target.
    fn search(&mut self, keys: &[TargetKey]) -> Result<Option<(Path, Which)>, AssessError> {
        if self.speech_start.is_none() || !self.has_nuclei {
            return Ok(None);
        }
        let mut tries = vec![(Which::Nuclei, Pass::Strict)];
        if self.count.is_some() {
            tries.extend([(Which::Count, Pass::Strict), (Which::Count, Pass::Relaxed)]);
        } else {
            tries.push((Which::Nuclei, Pass::Relaxed));
        }
        for (which, pass) in tries {
            let stage = match (which, &self.count) {
                (Which::Count, Some(count)) => count,
                _ => &self.nuclei,
            };
            if let Some(path) = best(stage, &mut self.scorer, self.dur_sigma, keys, pass)? {
                return Ok(Some((path, which)));
            }
        }
        Ok(None)
    }

    /// No complete path: every syllable sits at an empty span where the speech region starts
    /// (frame 0 without one), and the candidate scores `K × unvoiced_syllable_llr`.
    ///
    /// Without a nucleus in the analysis (silence, whisper) nothing could be measured: every
    /// syllable is `NotMeasured { Unvoiced }` ("tone not checked"). With nuclei the candidate
    /// just does not fit the syllables that were spoken (too many targets for the boundaries), so
    /// every syllable is a likely miss, `Partial { [NoNucleus] }` (rulings R33, R102).
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
                judgement: if self.has_nuclei {
                    missed(t, unvoiced)
                } else {
                    unmeasured(t, MeasureIssue::Unvoiced, unvoiced)
                },
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

/// [`best_path`] in `stage` for the targets behind `keys` under `pass`: a syllable with an anchor
/// scores its target's LLR on the anchor's evidence, one without scores `unvoiced_syllable_llr`,
/// each plus the duration prior of its span.
fn best(
    stage: &Stage,
    scorer: &mut Scorer<'_>,
    dur_sigma: f64,
    keys: &[TargetKey],
    pass: Pass,
) -> Result<Option<Path>, AssessError> {
    let unvoiced = f64::from(scorer.unvoiced_llr());
    best_path(&stage.bounds, &stage.filler, keys.len(), pass, |i, j, s| {
        let (from, to) = (stage.bounds[i], stage.bounds[j]);
        let d_s = f64::from(to - from) * FRAME_S;
        let llr = match stage.filler.nucleus_in(from, to) {
            Some(n) => f64::from(scorer.llr(stage.offset + n, keys[s])?),
            None => unvoiced,
        };
        Ok(llr + log_prior(d_s, stage.rate_s, dur_sigma))
    })
}

/// Clips the span of every syllable that holds no nucleus (`anchored[s]` false: relaxed pass
/// only) to the gap between the spans reported around it: from the end of the previous syllable's
/// final span to the start of the next nucleus-holding syllable's, or an empty span at the nearest
/// point of that gap if its own pair lies outside it.
///
/// The pairs of a path never overlap, but a nucleus's TBU can reach back over its syllable's own
/// pair (a nucleus on a boundary is bounded by the boundaries strictly around it), and a
/// nucleus-less pair next to it would then be reported over part of that TBU. After this, the
/// reported spans of a candidate run in time order without overlapping.
fn clip_unanchored(fits: &mut [SyllableFit], anchored: &[bool]) {
    for s in 0..fits.len() {
        if anchored[s] {
            continue;
        }
        let (from, to) = (fits[s].span.start_frame, fits[s].span.end_frame);
        let lo = s.checked_sub(1).map_or(from, |p| fits[p].span.end_frame);
        let next = (s + 1..fits.len()).find(|&n| anchored[n]);
        let hi = next.map_or(to, |n| fits[n].span.start_frame).max(lo);
        let start_frame = from.max(lo).min(hi);
        fits[s].span = TbuSpan {
            start_frame,
            end_frame: to.max(start_frame).min(hi),
        };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::convert::Infallible;

    /// Cost per uncovered nucleus in these tests (`insertion_llr = −2`).
    const INSERT: f64 = 2.0;

    /// A filler of `frames` frames at 1.0 per speech frame, speech wherever `speech(f)` holds,
    /// with `nuclei` at those frames and `insertion_llr = −INSERT`.
    fn filler(frames: usize, speech: impl Fn(usize) -> bool, nuclei: &[u32]) -> Filler {
        let mask: Vec<bool> = (0..frames).map(speech).collect();
        Filler::new(&mask, nuclei, 1.0, -INSERT)
    }

    fn path(
        bounds: &[u32],
        f: &Filler,
        k: usize,
        pass: Pass,
        score: impl Fn(usize, usize, usize) -> f64,
    ) -> Option<Path> {
        best_path::<Infallible>(bounds, f, k, pass, |i, j, s| Ok(score(i, j, s))).unwrap()
    }

    /// The syllable edges `best_path` offers for one target, as boundary-index pairs.
    fn offered(bounds: &[u32], f: &Filler, pass: Pass) -> Vec<(usize, usize)> {
        let mut seen = Vec::new();
        let _ = best_path::<Infallible>(bounds, f, 1, pass, |i, j, _| {
            seen.push((i, j));
            Ok(0.0)
        });
        seen
    }

    #[test]
    fn a_frame_at_the_speech_threshold_is_not_charged_as_speech() {
        // 20 frames at −100 dB put the quiet level there and the threshold at −90: a frame exactly
        // on it is not speech, as for the speech region and the pause edges (M8).
        let mut db = vec![-100.0; 20];
        db.extend([-90.0, -89.9, -20.0]);
        let mask = speech_mask(&EnergyTrack { db });
        assert_eq!(mask[20..], [false, true, true]);
    }

    #[test]
    fn filler_counts_speech_frames_and_nuclei_and_clamps_to_the_track() {
        let f = filler(10, |i| (2..6).contains(&i), &[]);
        assert_eq!(f.frames(), 10);
        assert_eq!(f.cost(0, 10), 4.0);
        assert_eq!(f.cost(3, 5), 2.0);
        assert_eq!(f.cost(6, 10), 0.0);
        assert_eq!(f.cost(0, 400), 4.0);
        assert_eq!(f.cost(5, 3), 0.0);
        // Nuclei count half-open, once per frame, and only on the track.
        let f = filler(10, |i| (2..6).contains(&i), &[3, 7, 3, 50]);
        assert_eq!(f.nuclei(0, 10), 2);
        assert_eq!((f.nuclei(3, 7), f.nuclei(4, 8), f.nuclei(0, 3)), (1, 1, 0));
        assert_eq!(f.nuclei(0, 400), 2);
        // Each uncovered nucleus costs −insertion_llr on top of the speech frames.
        assert_eq!(f.cost(0, 10), 4.0 + 2.0 * INSERT);
        assert_eq!(f.cost(6, 10), INSERT);
    }

    #[test]
    fn filler_absorbs_extra_speech_around_the_syllable() {
        // Speech everywhere; boundaries every 10 frames; one nucleus, at 15. Only 10 → 20 is a
        // good syllable.
        let f = filler(40, |_| true, &[15]);
        let bounds = [0, 10, 20, 30, 40];
        let good = |i, j, _| if (i, j) == (1, 2) { 50.0 } else { -50.0 };
        let p = path(&bounds, &f, 1, Pass::Strict, good).unwrap();
        assert_eq!(p.syllables, vec![(1, 2)]);
        // 10 leading and 20 trailing speech frames are charged as filler.
        assert_eq!(p.score, 50.0 - 30.0);
        // With a nucleus in every span, the three left over are insertions as well.
        let f = filler(40, |_| true, &[5, 15, 25, 35]);
        let p = path(&bounds, &f, 1, Pass::Strict, good).unwrap();
        assert_eq!(p.syllables, vec![(1, 2)]);
        assert_eq!(p.score, 50.0 - 30.0 - 3.0 * INSERT);
    }

    #[test]
    fn silent_frames_between_syllables_are_free() {
        // Two syllables separated by silence 20..30: the gap costs nothing.
        let f = filler(40, |i| !(20..30).contains(&i), &[15, 35]);
        let bounds = [0, 10, 20, 30, 40];
        let p = path(&bounds, &f, 2, Pass::Strict, |i, j, s| match (s, i, j) {
            (0, 1, 2) | (1, 3, 4) => 5.0,
            _ => -100.0,
        })
        .unwrap();
        assert_eq!(p.syllables, vec![(1, 2), (3, 4)]);
        assert_eq!(p.score, 10.0 - 10.0);
    }

    #[test]
    fn gap_edge_or_longer_syllable_whichever_scores_better() {
        // One target over speech 0..20 with its nucleus at 5: either the syllable 0 → 10 plus a
        // gap edge charging the 10 trailing speech frames (1 − 10 = −9), or one syllable over all
        // of 0 → 20.
        let f = filler(20, |_| true, &[5]);
        let bounds = [0, 10, 20];
        let score = |whole: f64| {
            move |i: usize, j: usize, _: usize| match (i, j) {
                (0, 1) => 1.0,
                (0, 2) => whole,
                _ => -100.0,
            }
        };
        let p = path(&bounds, &f, 1, Pass::Strict, score(-5.0)).unwrap();
        assert_eq!((p.syllables, p.score), (vec![(0, 2)], -5.0));
        let p = path(&bounds, &f, 1, Pass::Strict, score(-15.0)).unwrap();
        assert_eq!((p.syllables, p.score), (vec![(0, 1)], -9.0));
    }

    #[test]
    fn the_worst_syllable_is_the_one_left_as_an_insertion() {
        // Two targets over three 10-frame syllables of speech, one nucleus each: one syllable
        // has to be left over, costing its 10 frames of filler and an insertion.
        let f = filler(30, |_| true, &[5, 15, 25]);
        let bounds = [0, 10, 20, 30];
        let spans = |a: f64, b: f64, c: f64| {
            move |i: usize, j: usize, _: usize| match (i, j) {
                (0, 1) => a,
                (1, 2) => b,
                (2, 3) => c,
                _ => -100.0,
            }
        };
        let left_over = 10.0 + INSERT;
        let p = path(&bounds, &f, 2, Pass::Strict, spans(1.0, -30.0, 2.0)).unwrap();
        assert_eq!(
            (p.syllables, p.score),
            (vec![(0, 1), (2, 3)], 3.0 - left_over)
        );
        let p = path(&bounds, &f, 2, Pass::Strict, spans(-30.0, 1.0, 2.0)).unwrap();
        assert_eq!(
            (p.syllables, p.score),
            (vec![(1, 2), (2, 3)], 3.0 - left_over)
        );
        // Three targets use every syllable, however poor.
        let p = path(&bounds, &f, 3, Pass::Strict, spans(1.0, -30.0, 2.0)).unwrap();
        assert_eq!(
            (p.syllables, p.score),
            (vec![(0, 1), (1, 2), (2, 3)], -27.0)
        );
    }

    #[test]
    fn strict_syllables_hold_exactly_one_nucleus_relaxed_at_most_one() {
        // Nuclei at 15 and 35 between boundaries every 10 frames.
        let f = filler(40, |_| true, &[15, 35]);
        let bounds = [0, 10, 20, 30, 40];
        let strict = offered(&bounds, &f, Pass::Strict);
        assert_eq!(strict, vec![(0, 2), (0, 3), (1, 2), (1, 3), (2, 4), (3, 4)]);
        // Relaxed adds the nucleus-less spans, never one with two nuclei (0 → 40, 10 → 40).
        let relaxed = offered(&bounds, &f, Pass::Relaxed);
        assert_eq!(
            relaxed,
            vec![
                (0, 1),
                (0, 2),
                (0, 3),
                (1, 2),
                (1, 3),
                (2, 3),
                (2, 4),
                (3, 4)
            ]
        );
    }

    #[test]
    fn a_target_cannot_hide_on_a_sliver_without_the_nucleus() {
        // One syllable 0..30 with its nucleus at 25 and interior boundaries at 10 and 20. The
        // target fits the slivers 0 → 10 and 10 → 20 far better than the syllable, yet a strict
        // syllable must hold the nucleus.
        let f = filler(30, |_| true, &[25]);
        let bounds = [0, 10, 20, 30];
        let p = path(&bounds, &f, 1, Pass::Strict, |i, j, _| match (i, j) {
            (0, 1) | (1, 2) => 5.0,
            (0, 3) => -8.0,
            _ => -20.0,
        })
        .unwrap();
        assert_eq!((p.syllables, p.score), (vec![(0, 3)], -8.0));
    }

    #[test]
    fn uncovered_nuclei_pay_the_insertion_wherever_they_are() {
        // Silence everywhere (no per-frame filler), a nucleus in each of three spans.
        let f = filler(30, |_| false, &[5, 15, 25]);
        let bounds = [0, 10, 20, 30];
        // The middle one as the syllable: the leading and trailing nuclei are insertions.
        let middle = |i, j, _| if (i, j) == (1, 2) { 0.0 } else { -100.0 };
        let p = path(&bounds, &f, 1, Pass::Strict, middle).unwrap();
        assert_eq!((p.syllables, p.score), (vec![(1, 2)], -2.0 * INSERT));
        // The outer two as syllables: the gap edge between them holds an insertion.
        let outer = |i, j, _| {
            if (i, j) == (0, 1) || (i, j) == (2, 3) {
                0.0
            } else {
                -100.0
            }
        };
        let p = path(&bounds, &f, 2, Pass::Strict, outer).unwrap();
        assert_eq!((p.syllables, p.score), (vec![(0, 1), (2, 3)], -INSERT));
    }

    #[test]
    fn relaxed_pass_places_more_targets_than_nuclei() {
        // Two nuclei, three targets: no strict path; the relaxed one puts a target on the
        // nucleus-less span between them.
        let f = filler(30, |_| true, &[5, 25]);
        let bounds = [0, 10, 20, 30];
        assert!(path(&bounds, &f, 3, Pass::Strict, |_, _, _| 0.0).is_none());
        let p = path(&bounds, &f, 3, Pass::Relaxed, |_, _, _| 0.0).unwrap();
        assert_eq!(p.syllables, vec![(0, 1), (1, 2), (2, 3)]);
    }

    #[test]
    fn syllable_edges_respect_the_duration_window() {
        let f = filler(200, |_| true, &[]);
        // Spans of 5 frames (50 ms) and 81 frames are out; 6 (60 ms) and 80 (800 ms) are in.
        let bounds = [0, 5, 6, 86, 87];
        let seen: Vec<(u32, u32)> = offered(&bounds, &f, Pass::Relaxed)
            .into_iter()
            .map(|(i, j)| (bounds[i], bounds[j]))
            .collect();
        assert_eq!(seen, vec![(0, 6), (6, 86)]);
    }

    #[test]
    fn no_path_when_too_few_boundaries() {
        let f = filler(40, |_| true, &[5, 15, 25, 35]);
        // Three boundaries allow at most two syllables.
        assert!(path(&[0, 10, 20], &f, 3, Pass::Relaxed, |_, _, _| 0.0).is_none());
        assert!(path(&[0, 10, 20], &f, 2, Pass::Strict, |_, _, _| 0.0).is_some());
        // Spans shorter than 60 ms are never syllables.
        assert!(path(&[0, 3], &f, 1, Pass::Relaxed, |_, _, _| 0.0).is_none());
        assert!(path(&[], &f, 1, Pass::Relaxed, |_, _, _| 0.0).is_none());
    }

    #[test]
    fn scorer_errors_propagate() {
        let f = filler(40, |_| true, &[5]);
        let r = best_path(&[0, 10, 20], &f, 1, Pass::Strict, |_, _, _| {
            Err::<f64, _>("boom")
        });
        assert_eq!(r, Err("boom"));
    }

    #[test]
    fn unanchored_spans_are_clipped_to_the_gap_between_their_neighbours() {
        use crate::test_support::target;
        let fits = |spans: &[(u32, u32)]| -> Vec<SyllableFit> {
            spans
                .iter()
                .map(|&(start_frame, end_frame)| SyllableFit {
                    span: TbuSpan {
                        start_frame,
                        end_frame,
                    },
                    judgement: missed(&target("1", None), -3.0),
                })
                .collect()
        };
        let clipped = |spans: &[(u32, u32)], anchored: &[bool]| -> Vec<(u32, u32)> {
            let mut f = fits(spans);
            clip_unanchored(&mut f, anchored);
            f.iter()
                .map(|x| (x.span.start_frame, x.span.end_frame))
                .collect()
        };
        let (yes, no) = (true, false);
        // A span inside its gap stays; one reaching into either neighbour is cut back to it.
        assert_eq!(
            clipped(&[(10, 35), (38, 44), (50, 70)], &[yes, no, yes]),
            [(10, 35), (38, 44), (50, 70)]
        );
        assert_eq!(
            clipped(&[(10, 35), (30, 55), (50, 70)], &[yes, no, yes]),
            [(10, 35), (35, 50), (50, 70)]
        );
        // Nothing left, in either direction: empty, at the nearest point of the gap.
        assert_eq!(
            clipped(&[(10, 35), (35, 41), (35, 66)], &[yes, no, yes]),
            [(10, 35), (35, 35), (35, 66)]
        );
        assert_eq!(
            clipped(&[(10, 40), (20, 30), (45, 70)], &[yes, no, yes]),
            [(10, 40), (40, 40), (45, 70)]
        );
        // Neighbours that overlap each other (TBUs never do) leave an empty span, not an inverted
        // one.
        assert_eq!(
            clipped(&[(10, 60), (30, 50), (40, 70)], &[yes, no, yes]),
            [(10, 60), (60, 60), (40, 70)]
        );
        // Without a neighbour on a side, that side is the span's own; unanchored ones in a row
        // are clipped one after the other.
        assert_eq!(clipped(&[(10, 20)], &[no]), [(10, 20)]);
        assert_eq!(
            clipped(&[(0, 12), (12, 30), (30, 50)], &[no, yes, no]),
            [(0, 12), (12, 30), (30, 50)]
        );
        assert_eq!(
            clipped(
                &[(10, 30), (30, 45), (45, 60), (60, 80)],
                &[yes, no, no, yes]
            ),
            [(10, 30), (30, 45), (45, 60), (60, 80)]
        );
        assert_eq!(
            clipped(
                &[(10, 40), (30, 50), (50, 55), (45, 80)],
                &[yes, no, no, yes]
            ),
            [(10, 40), (40, 45), (45, 45), (45, 80)]
        );
        assert!(clipped(&[], &[]).is_empty());
    }

    #[test]
    fn a_nucleus_less_syllable_reports_only_the_gap_its_neighbours_leave() {
        // Nuclei at frames 22 and 41, the second one on a boundary, so its TBU (35, 66) starts
        // before its syllable's pair does. Three targets need the relaxed pass: pairs (10, 35),
        // (35, 41) and (41, 66), of which the middle one holds no nucleus. Its own pair would
        // overlap the TBU of the syllable after it (R55); it reports what the TBUs leave: none.
        use crate::test_support::{cmn, hand, marked, std_g, target};
        use tonekit_core::{CandidateId, Measured, Nucleus};
        let mut a = marked(hand(&[&[5.0, 1.0], &[2.0, 1.0]]));
        assert_eq!(a.boundaries, [10, 35, 41, 66]);
        a.nuclei = [22, 41]
            .map(|frame| Nucleus {
                frame,
                strength_db: 20.0,
            })
            .to_vec();
        let cand = Candidate {
            id: CandidateId("c".into()),
            targets: vec![target("4", None), target("1", None), target("3", None)],
        };
        let r = crate::decode(&a, &cmn(), &std_g(), &[cand]).unwrap();
        let s = &r.candidates[0].syllables;
        let spans: Vec<(u32, u32)> = s
            .iter()
            .map(|f| (f.span.start_frame, f.span.end_frame))
            .collect();
        assert_eq!(spans, [(10, 35), (35, 35), (35, 66)], "{s:#?}");
        assert_eq!(
            s[1].judgement.measured,
            Measured::Partial {
                issues: vec![MeasureIssue::NoNucleus]
            }
        );
        assert!(matches!(s[0].judgement.measured, Measured::Full));
        assert!(matches!(s[2].judgement.measured, Measured::Full));
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
