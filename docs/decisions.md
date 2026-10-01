# Decisions

The choices that shaped tonekit's behaviour, data and build, numbered `R1` to `R62`. Code comments
and tests cite them as "ruling R27" or just `R27`; this is where they are written down. Each entry
says what was decided, why, and what it costs if it turns out wrong. The spec
([`docs/superpowers/specs/`](superpowers/specs/2026-09-28-tone-assessment-design.md)) says what
tonekit is meant to do; these entries are the places where the spec was ambiguous, contradicted
itself or could not be built as written, and the answer is now fixed.

An entry can amend an earlier one (R48 amends R47, R50 supersedes part of R33). The latest entry
on a point wins. Entries about how the work was organised are one line each under
[Process](#process).

## Build and repository

### R1: Workspace layout

**Decision.** The workspace `Cargo.toml` uses `members = ["crates/*"]` and sets
`[profile.dev.package."*"] opt-level = 3`. No change adds a crate by editing `members`.
**Why.** A glob means a new crate never touches a shared file, and optimised dependencies keep the
DSP tests fast in debug builds. **Cost if wrong.** None: the glob is standard. Debug builds compile
dependencies more slowly.

### R2: Separate CI jobs for the Python pieces

**Decision.** The evaluation harness (`harness`) and the Python bindings (`python-bindings`) have
their own CI jobs, not one shared Python job. **Why.** They were built at different times and fail
independently. **Cost if wrong.** Two jobs, and two `uv sync` builds, instead of one; they are
trivially merged later.

### R21: One ignored advisory

**Decision.** `deny.toml` ignores RUSTSEC-2024-0436 (the `paste` crate is unmaintained), with the
reason written beside it. `paste` is a build-time proc macro reached through
`pyin → statrs → nalgebra → simba`; it is not a vulnerability. Revisit when pyin's dependencies
move. **Why.** The alternative is a failing policy check for something that cannot be acted on.
**Cost if wrong.** An unmaintained build-time macro stays in the dependency tree.

### R22: Optimised `tonekit-f0` in debug builds

**Decision.** The workspace `Cargo.toml` adds `[profile.dev.package.tonekit-f0] opt-level = 3`.
**Why.** pYIN is generic, so it compiles inside `tonekit-f0` and not inside the optimised `pyin`
dependency; unoptimised it is about ten times slower, which made the test suite crawl. **Cost if
wrong.** Stepping through `tonekit-f0` in a debugger is harder.

### R42: Minimum supported Rust is 1.85

**Decision.** The workspace `rust-version` is 1.85, and CI builds the workspace on exactly that
toolchain (the `msrv` job). **Why.** Several dependencies (proptest, indexmap, clap) already need
1.85, so the declared floor of 1.82 was false. **Cost if wrong.** None.

### R44: One licence exception for `target-lexicon`

**Decision.** `deny.toml` gets a crate-scoped exception allowing `target-lexicon` under
`Apache-2.0 WITH LLVM-exception`. **Why.** It is used only at build time (by `pyo3-build-config`),
is never linked into the iOS library, and the LLVM exception only relaxes Apache-2.0. The
exception is scoped to the crate, like the UniFFI ones, rather than allowing the expression
globally. **Cost if wrong.** None that matters.

## Signal, shape and scoring

### R3: What "energy" measures

**Decision.** Frame energy is `10·log10(Σ w²x² / Σ w²)` over a 400-sample Hann window centred on
each 160-sample hop, floored at −100 dB. A full-scale sine reads −3.0 dB. **Why.** Dividing by the
window's energy makes the level independent of the window shape, so a full-scale sine reads the
familiar −3.0 dB; without it the reading is −4.3 dB. **Cost if wrong.** Absolute dB offsets differ
from other tools. Every use in tonekit is relative (thresholds are taken against the p10 frame
level), so the effect is small.

### R4: The turning point of a contour

**Decision.** `turning_point` is the position (0 to 1) of the interior minimum or maximum of the
3-frame-smoothed voiced semitone curve, reported only when it lies in (0.1, 0.9) and stands at
least 0.5 Chao units beyond both endpoints (if both a minimum and a maximum qualify, the larger
excursion). `curvature` stays the quadratic coefficient of a least-squares fit. **Why.** The spec
says "interior min/max only". The quadratic's vertex, which the first plan used, sits at 0.366 for a
[2, 1, 4] dip, where the lowest point is at the middle. **Cost if wrong.** Turning-point advice
shifts slightly; it is easy to swap.

### R5: A register with nothing to learn from

**Decision.** `cold_register` on empty input returns floor 90 Hz, median 150 Hz, ceiling 250 Hz
(as semitones re 55 Hz) with `n_syllables` 0; `merge_register` with nothing to merge returns the
register as it was (R38 sharpens what counts). **Why.** This is only reachable when nothing is
voiced, where shapes are unmeasured anyway. **Cost if wrong.** None observable.

### R7: The creak test compares like with like

**Decision.** In the pack crate's test that a creaky gap is not penalised, the clean baseline is
judged in the same context (final position, preceding tone 1) as the creaky shape. **Why.** The
first version compared a clean shape in a default context with a creaky one in a final context,
which is not a comparison of creak. **Cost if wrong.** None.

### R8: How the tests speak tones

**Decision.** Tests that need spoken tones use one convention: tone 1 is [5, 5], tone 2 is [3, 5],
tone 4 is [5, 1], and tone 3 is [2, 1] when not phrase-final and the full dip [2, 1, 4] when
phrase-final. **Why.** The spec realises a non-final third tone as a half third; a test that spoke a
full dip in the middle of a phrase would be testing the wrong thing. **Cost if wrong.** None: the
intent of the tests (tone-minimal discrimination) is unchanged.

### R9: Thresholds in the end-to-end test

**Decision.** The facade's correct-versus-wrong test analyses with a warm register and asserts
correct overall > 0.6, wrong overall < 0.3 and a gap above 0.4. **Why.** With the seed calibration
`p_correct` cannot exceed `1 / (1 + prior_target)`, so the original "> 0.7" was unreachable for a
tone-4 target; fitting the calibration in P1 stretches the range. **Cost if wrong.** A weaker P0
unit test. The gate uses leave-one-pair-out thresholds, so it is unaffected.

### R12: Every number crossing JSON is finite

**Decision.** All log-likelihoods, log-likelihood ratios and posteriors that leave the library are
finite: log values are clamped to −1.0e6 and NaN or infinity is never emitted. **Why.** `serde_json`
writes a non-finite float as `null`, which then fails to deserialise on the other side. **Cost if
wrong.** A clamp that hides a true −∞, visible as −1e6 in the output.

### R14: How loud the test-voice noise is

**Decision.** The synthetic test voice adds Gaussian noise with σ equal to 0.1 (or 0.05) of the
peak of its harmonic layer, before normalising. **Why.** The wording "amplitude 0.1/0.05 of the
voiced peak" was ambiguous; only the relative levels matter to the tests that use it. **Cost if
wrong.** Whisper and creak noise are about 1.8 times louder than a nominal-peak reading would
give; the tests re-tune trivially.

### R19: What `overall` means

**Decision.** `overall` is the minimum `p_correct` over the syllables that were measured or that
carry a confusion-set hit, and is `None` only when no syllable has either. A whispered syllable
that hits the confusion set therefore counts as a miss. **Why.** "Tone not checked" is reserved for
syllables with no tone evidence at all. A confusion hit on a whispered syllable is still a miss, as
in a transcript-plus-confusion-set check. **Cost if wrong.** A whispered utterance with a hit
fails where the older rule said "not checked"; that is the intended product behaviour.

### R23: How tight a shape match can be

**Decision.** Tests on shapes extracted from audio allow about 0.15 Chao units of contour jitter on
steep tones, and the time-stretch invariance test scales its bound with the slope of the contour
(about 0.036 × slope per unit of time). Hand-built shapes in tests are exact. **Why.** On a 10 ms
frame grid a 5→1 fall cannot hold ±0.1 under a 10% time stretch (it moves by 0.144); a 2→1→4 dip
moves by 0.217. The gap is a sampling limit, not a bug. **Cost if wrong.** A looser invariant than
originally written.

### R24: pYIN's pitch is aligned to the frame grid

**Decision.** `Pyin::track` advances the signal by 200 samples (drops the first 200, zero-appends
200) before running pYIN, which leaves at most about ±0.3 frame of residual lag over 80 to 300 Hz.
The documentation's claims about alignment were corrected to match. **Why.** The YIN template is
the first 512 samples of the 1024-sample frame, so pitch lagged about 1.3 frames (13 ms) behind
the energy track, which is exactly centred; the contract is that frame *i* is centred on sample
*i*·160. **Cost if wrong.** About ±3 ms of misalignment at the extremes of pitch.

### R25: Contour windows at the ends of the voiced part

**Decision.** The windows that read a contour's ends narrow to one frame at each end of the voiced
part, instead of a ±5% window clipped on one side. **Why.** It is unbiased on slopes. **Cost if
wrong.** Onset and offset readings are noisier on real pYIN edges; revisit when calibration is
fitted on real recordings, where it would show as wider calibrated σ.

### R26: Very short syllables are compared on onset and offset only

**Decision.** Under the `TooShort` issue, shape deltas are limited to the start and end terms; no
turning-point or range advice. **Why.** The spec (§12) says onset and offset only, and advice must
not come from a contour the scorer does not trust. **Cost if wrong.** Less feedback on very short
syllables.

### R37: The margin is measured against the same null as the posterior

**Decision.** `margin_llr` is the intended reading's log-likelihood ratio minus the larger of the
best other candidate's and `null_llr + null_bias`. **Why.** The raw null (the best free tone at
every nucleus) is at least as good as any candidate by construction, so the spec's first definition
made the margin zero or negative even for correct readings. Using the biased null, which the
posterior softmax already uses, puts both on one scale. **Cost if wrong.** The margin shifts by a
constant (`null_bias`); rank is unaffected.

### R38: What updates the register

**Decision.** `register_update` merges only syllables that were actually measured, with `u` equal to
their count. If `u` is 0 the given register comes back unchanged (its `n_syllables` is not
incremented), and a cold start returns the fallback register with `n_syllables` 0. Apps persist a
register only when `n_syllables > 0`. **Why.** Whispered or silent casts must not advance the
cold-start counter. **Cost if wrong.** Warm-up takes a few more voiced casts.

### R60: A pitch the signal repeats at half the period of is doubled

**Decision.** Before octave repair, every voiced frame's pitch is doubled when the 512 samples
around it repeat at half the tracked period at least as well as at the period itself: the
normalised square-difference function at half the period, best over integer lags within 2 samples,
is at least 0.5 and at least the full period's minus 0.05; and twice the pitch is within pYIN's
600 Hz ceiling. It applies to pYIN and external tracks alike (`repair_subharmonics`, then
`repair_octaves`). **Why.** pYIN carries its pitch across a short unvoiced stretch, so when a tone 4
ending at the floor runs into a tone 1 an octave higher it can track the whole tone 1 on the
subharmonic (a 110-260 Hz speaker's tone 1 read at 129.7 Hz, graded 0.000). Every frame of that run
agrees with its neighbours, so run-local octave repair (R32) cannot see it; the signal can. **Cost if
wrong.** A voice with most of its energy in even harmonics could be doubled; a second harmonic at
twice the first's amplitude repeats at 0.6 against 1.0, well clear of the rule. About ten
512-sample lags per voiced frame.

## Decoding

### R27: Nuclei look at periodicity, and pauses are boundaries

**Decision.** A syllable nucleus counts as voiced when any frame within ±2 of its energy peak has
`hz.is_some()` (periodicity), not when `voiced_p ≥ 0.5`. Candidate boundaries also include the
crossings of the speech threshold (interior pauses). When there are too many, the cap keeps them in
this order: edges, inter-nucleus minima, threshold crossings, voicing edges, interior minima.
**Why.** Real pYIN leaves accurate pitch on frames whose confidence is 0.24 to 0.62 (a fast
falling [5, 1] syllable), so a confidence test lost whole syllables. The decoder can only place a
syllable on a candidate boundary, so a missed edge cannot be recovered downstream. **Cost if
wrong.** More spurious nuclei on noisy periodic non-speech such as café noise with music, bounded
by the cap.

### R28: Pause edges come from raw frame levels

**Decision.** The pause tier of boundaries uses crossings of the raw frame dB against the speech
threshold (the signal `speech_region` uses), not the smoothed dB. `boundaries_with` takes explicit
segmentation parameters and `boundaries` delegates with the defaults. **Why.** The 5-frame smoothing
smeared edges 2 to 3 frames into 6-frame gaps, and de-duplication then dropped real edges. **Cost
if wrong.** Raw crossings can flicker on noisy input; de-duplication and the cap bound it.

### R30: The pack crate exports its log-sum-exp

**Decision.** `tonekit-pack` exports `logsumexp` (with a unit test) and the decoder uses it rather
than a private copy. **Why.** One numerically stable implementation shared by scoring and decoding.
**Cost if wrong.** None.

### R32: A voiced frame is a frame with a pitch

**Decision.** A voiced frame is `hz.is_some()` everywhere: shape extraction, `voiced_semitones`,
register estimation and octave repair. `voiced_p` stays a confidence weight. Octave repair takes its
neighbour median only within the frame's own voiced run (contiguous voiced frames, bridging gaps of
up to 2), and leaves runs of fewer than 5 voiced frames alone. **Why.** pYIN's own voicing decision
is the pitch track's ground truth, and R27 already relies on it for nuclei. A median taken across
syllables let a legitimate 4→1 jump between syllables anchor a wrong correction and missed a clean
octave error. **Cost if wrong.** Noisy periodic frames enter contours; octave repair and the pack's
σ absorb isolated ones.

### R33: Closed-set decoding cannot hide a nucleus

**Decision.** (1) A closed-set syllable edge must contain exactly one nucleus. (2) A gap edge that
covers a nucleus pays `insertion_llr` (seed −2.0) on top of the per-frame filler. (3) If no strict
path exists and the analysis has at least one nucleus, a relaxed pass allows at most one nucleus
per syllable, and a nucleus-less syllable scores `unvoiced_syllable_llr` and is reported as
`Partial { [Unvoiced] }`, so it counts toward `overall` as a likely miss. (4) The all-`NotMeasured`
fallback ("tone not checked") is reserved for utterances with zero nuclei. **Why.** "Not checked"
must mean "no voiced speech", never "the wrong tone was hidden by the segmentation". **Cost if
wrong.** A dropped or merged syllable in voiced speech reads as a miss instead of "not checked";
that is the intended gate behaviour. R50 changes where the evidence comes from, not these rules.

### R34: Boundary voicing edges follow pitch, not confidence

**Decision.** Boundary candidates at voicing edges sit at `hz.is_some()` transitions rather than
where `voiced_p` crosses 0.5. **Why.** R32 says "everywhere", and `voiced_p` flicker otherwise cut
boundaries inside syllables. **Cost if wrong.** One hunk in `boundaries.rs`; the segment tests do
not change.

### R35: How R33 is applied at the edges

**Decision.** `insertion_llr` is charged per uncovered nucleus, leading and trailing ones included.
When there is no path at all but nuclei exist, all K syllables are `Partial { [Unvoiced] }`.
"Fewer than 5 voiced frames" is the definition of a short run in R32. The spec's "whisper" row
means "no nucleus in the speech region". **Why.** Each follows the intent of R33 and R32. **Cost if
wrong.** Small, and visible in spec §7.2 and §12.

### R36: Hesitations lose to the null competitor (open)

**Decision.** With `insertion_llr` −2 and `null_bias` −2, a hesitation ("嗯") before a spell loses
to the null competitor (posterior about 0.05 against 0.95). P0 grading uses `overall` and the
intended reading's rank among the candidates, not the null posterior, so this is left as it is; P1
fits `insertion_llr` and `null_bias` on hesitation clips and re-measures after R50. **Why.** The
seeds are unfitted, and fitting them on synthetic audio is not allowed (spec §9). **Cost if wrong.**
Consumers that read the candidate posterior in P0 see hesitations as "something else".

### R39: Optional request fields

**Decision.** `AssessRequest` fields `distractors`, `external` and `compare_accents` default when
omitted (`#[serde(default)]`). **Why.** JSON callers (the CLI, Python) should not have to send empty
lists. **Cost if wrong.** None.

### R50: Syllable tone evidence does not depend on the candidate

**Decision.** Each nucleus's shape is extracted once, on its own tone-bearing unit (TBU) span (the
nearest boundaries around the nucleus, with the voiced part restricted to the nucleus's own voiced
run), and the closed-set decoder scores a syllable segment containing nucleus *n* with the
likelihood ratio of that one shape against the candidate's target and context. Boundary pairs keep
only the duration prior and the filler, insertion and null accounting. The open lattice uses the
same per-nucleus shapes. This replaces extracting a shape per candidate on the boundary pair the
search chose for it (amending spec §7.2 and the scoring of R33). **Why.** The spec grades the tone the speaker
produced. When each candidate chose its own span, a wrong target could pick a span reaching into the
gap (pYIN reports "voiced" frames next to syllable edges, even in digital silence), bend the contour
and score as high as the correct reading: intended "4 2 3" on a spoken 4-1-3 scored 0.795 on the
middle syllable against 0.734 for the correct reading. Shared evidence also makes the closed-set
and lattice results identical. **Cost if wrong.** A mis-segmented boundary can no longer be absorbed
per candidate, so segmentation errors surface as tone errors, bounded by R33's one-nucleus-per-
syllable anchoring. A substitution sweep in CI measures it. R55 says which span a syllable then
reports.

### R51: R47 and R48 stand after R50

**Decision.** Keep the R47 mixture and the R48 direction-with-margin tests, re-measure both on the
corrected decoder with the shipped pack and the earlier pack, and require the committed tests to
hold. **Why.** Much of R47's motivation was the span-shopping defect of R50. **Cost if wrong.**
Non-final tone 3 is slightly lenient to full dips, as before.

### R55: A syllable reports where its tone was measured

**Decision.** After R50, `SyllableFit.span` is the nucleus's TBU span, the stretch the tone evidence
was measured on, and not the boundary pair the decoder chose. The closed-set spans therefore equal
the lattice spans. **Why.** The boundary pair is now chosen by the duration prior and the filler
accounting alone, so it drifts into the gaps between syllables; consumers such as the harness
perturbations and Bendy's highlighting need to know where the syllable's tone is. **Cost if wrong.**
A consumer that wants the decoder's segmentation for a duration display loses it; nothing uses it
yet.

### R56: The CI substitution sweep runs on a warm register

**Decision.** The sweep asserts on a warm register, which is the condition of gate S1 (R46). On a
cold register a tone 2 target on a spoken tone 1 scores 0.63 to 0.67 (5 of the sweep's 54 cases per
condition reach 0.5), always below the spoken tone's 0.70 to 0.72; that compression is left to the
P1 calibration of the temperature and β on the owner's data, not treated as a decoder defect.
**Why.** The seeds are unfitted, and fitting them on synthetic audio is not allowed (spec §9).
**Cost if wrong.** Bendy's first-session feedback, given on a cold register, is lenient on tones 1
and 2 until the register warms at 30 syllables.

### R58: Every long voiced run holds a nucleus

**Decision.** A long voiced run (at least 5 voiced frames, gaps of up to 2 bridged: R32, R35) inside
the speech region with no energy peak adds a nucleus candidate at its highest smoothed level, unless
some frame within 2 of that is more than `dip_db` louder (the flank of a louder unvoiced peak). A
candidate within 2 frames outside a long run moves onto the run's nearest frame. Two candidates in
different long runs merge only when they are closer than `min_nucleus_gap`, never on a shallow
valley alone. One definition of a run (`voiced_runs`, `MIN_RUN_FRAMES` in `tonekit-core`) now serves
octave repair, nuclei and shape extraction. **Why.** Fluent speech joins syllables with no dip in
level; where the voice moves fast from one tone to the next, pYIN loses the pitch for a few frames,
and that pitch break is then the only sign of the join. Under R50 a run without a nucleus is
evidence nobody measures. On the fluent sweep at 0 dB every clip was one nucleus; now only joins with
no pitch break are missed (R62). **Cost if wrong.** A dropout of 3 or more frames inside one
syllable (the creaky bottom of a tone 3) with less than a 2 dB dip now splits it into two nuclei: the
tone is measured on one part and the other is charged as an insertion (R33). A dip of more than 2 dB
already split it before.

### R59: Between nuclei on a level, the boundary is the pitch break

**Decision.** When two adjacent nuclei lie in different long voiced runs and the smoothed level
between them dips by no more than `dip_db`, their inter-nucleus boundary candidates are the pitch
break's edges (the frame after the first run's last voiced frame, and the second run's first voiced
frame) instead of the level's minimum. **Why.** The minimum of a flat level is noise, and as a TBU
edge (R50) it cut a syllable's own voiced run short. **Cost if wrong.** None seen: with a real dip
(any gapped speech) the minimum stands as before, and the fixture did not move.

### R61: A coarticulated join is transition, not tone

**Decision.** At a TBU edge where the speech runs on (every frame within 3 on either side is a
speech frame) and the pitch runs on (the frames either side of the edge are both voiced), the 3
frames (30 ms) beside the edge, at most a quarter of the TBU, are left out of the nucleus's voiced
part. The reported span (R55) is unchanged. **Why.** In fluent speech the boundary sits at the join,
in the middle of the pitch's glide from one tone to the next: a tone 2 after a tone 1 started at
Chao 4.3 instead of 3 and graded as tone 1 at 0.62 to 0.68. Pauses, consonants, the speech region's
edges and pitch breaks are not joins, so gapped speech is untouched. Requiring the pitch on both
sides keeps pYIN's dropouts inside a fast falling tone 4 from being trimmed as joins. **Cost if
wrong.** Real carryover from the previous tone lasts longer than 30 ms, so onsets keep some of it;
and at a join a tone's own first or last 30 ms is not measured, which P1's calibration on real
speech absorbs.

### R62: The fluent sweep's known gaps

**Decision.** The CI fluent sweep (`fluent_sweep.rs`) asserts three conditions (5 syllables/s with
no dip; 5/s with a 6 dB dip; 6/s with a 3 dB dip at 25 dB SNR) for four speakers and the six
substitution-sweep readings, except six named gaps. At 0 dB, 1-2-3, 4-1-2 and 2-4-1 (every speaker)
and 4-1-3 (the 110-260 Hz speaker) are reported, not asserted. At 6/s, that speaker's 2-3-4 and
3-4-1 must segment and rank the spoken tone first, but a wrong tone may reach 0.5. A gap that starts
passing is reported. A report-only matrix covers 4 to 6 syllables/s, 0 to 12 dB, 30 or 60 ms glides,
a fricative onset and 20 dB SNR. **Why.** With no level dip and the pitch tracked straight through
(a 2-Chao glide from tone 1 to tone 2, or tones 2 and 4 meeting at the ceiling), no energy or
periodicity cue separates the syllables. Finding them needs a pitch-landmark cue, which the design
(R27, R32, R33, R50) does not have and which is a design decision, not a fix. The 6/s gaps are a
15-semitone fall in about 150 ms, faster than the measured human maximum speed of pitch change:
pYIN loses its ends and the middle fits tone 3 too. **Cost if wrong.** A native speaker who runs a
tone 1 into a tone 2, or a tone 2 into a tone 4, with no consonant and no dip at all is graded as
missing a syllable (R33). Real speech nearly always has an initial consonant or glide, which gives
a dip or a pitch break.

## Packs and calibration

### R16: The seed pack is audited at P1

**Decision.** `cmn.toml` is verbatim from the approved spec (§6.2); the owner's audit of its seed
values moves to the calibrated pack in P1. **Why.** The values are citation tone letters and accent
realisations, not fitted numbers, and the spec was approved with them. **Cost if wrong.** A
seed-value error surfaces in P0 gate diagnostics instead of at audit.

### R17: Pack provenance files

**Decision.** A pack's `PROVENANCE.toml` has a top-level `artifact` (one path) or `artifacts` (a
list of paths) and a `note`, plus optional `[[source]]` tables (`id`, `use`) and `[[signoff]]`
tables (`id`, `by`, `date`, `note`). A file with no `[[source]]` has zero sources. Paths are
relative to the repository root. **Why.** One format shared by the pack loader and the checker
(`tkh provenance`); a pack has more than one data file, so a single `artifact` was not enough.
**Cost if wrong.** A format mismatch caught at the check.

### R20: The provenance check is strict

**Decision.** A provenance file has exactly the keys `artifact` or `artifacts`, `note`, `source`
and `signoff`; `note` and each artifact are non-empty strings; each signoff needs a non-empty `by`.
`tkh provenance --packs-root DIR` fails if any pack directory lacks a `PROVENANCE.toml`, if an
artifact does not exist or lies outside its pack directory, or if any `*.toml` or `*.json` file in
the pack directory (other than `PROVENANCE.toml`) is not listed. **Why.** A misspelt key must not
look like a clean zero-source file, and a data file that nobody attested (the pack TOML itself, an
extra calibration) must not slip through. **Cost if wrong.** A stricter gate than first written;
strictness is the point.

### R41: Fixtures are compared within tolerance

**Decision.** Comparisons against the shared fixture are tolerance-based: regenerated WAV samples
within 1e-6, and assessment JSON by parsed value within 1e-4 per float (exact for strings and
integers). Every front end (the CLI, Swift, Python) reads the checked-in WAV and compares to the
checked-in JSON within 1e-4. **Why.** Synthesised audio and pYIN go through the platform's libm, so
an aarch64 Mac need not match the Linux bits exactly. **Cost if wrong.** A real regression below
1e-4 slips past the fixture test; the dedicated unit tests still catch behaviour.

### R46: The register protocol for the gate corpus

**Decision.** The recording protocol's `register` set is 妈麻马骂 ×8 (32 syllables), so the total
recorded set is 128 clips. **Why.** That is above the 30-syllable cold-start threshold, so gate
clips are graded with a warm register and no ×1.5 tolerance widening; a 12-syllable register left
every gate clip cold. **Cost if wrong.** The recording session takes five more short clips.

### R47: Non-final tone 3 is a mixture

**Decision.** In `cmn.toml` the non-final tone-3 rule `t3-half` is a mixture of [2, 1] (weight 0.75)
and [2, 1, 4] (weight 0.25), with its label kept. **Why.** A full dip in a non-final position, the
classic over-production by learners, fitted tone 2 better than the half third did, so a
tone-3-for-tone-2 error was accepted. With the mixture, tone 3 explains a full dip, the background
swamps tone 2, and the error is caught, while an intended tone 3 spoken as a full dip still gets
partial credit. Packs are data (spec §6.1); the weight is the linguistically grounded share for
native non-final tone 3, not a value tuned on synthetic audio. **Cost if wrong.** Non-final tone 3
grading is slightly more lenient to full dips.

### R48: The R47 regression asserts a direction with a margin

**Decision.** The regression tests for R47 keep the mixture at 0.75 / 0.25 and assert direction
with margin: the error's overall score is at most the correct reading's minus 0.03, and an intended
tone 3 spoken as a full dip scores above 0.65 on that syllable. A warm-register variant is
measured and reported only. **Why.** Choosing the weight from a sweep on synthetic audio would be
calibrating on synthetic data, which the spec forbids (§9, §11); posteriors are compressed at the
seed calibration (a perfect synthetic tone 1 scores 0.71 cold), so absolute sharpness is the P1
calibration's job. **Cost if wrong.** The T2/T3 diagnostic shows weak tone-3-for-tone-2 detection
in the P0 gate, and the fix moves to P1 calibration or a confusion rule, not to pack weights.

## Data, licensing and the gate

### R11: The gate is measured on real recordings

**Decision.** The owned recording corpus and the gate run belong to the project owner; the harness
is proven on synthetic clips so real recordings drop straight in. The harness never issues an S1
verdict over synthetic audio: `tkh eval` and `tkh bakeoff` print PASS or FAIL only when every clip
is a real recording whose source the data register allows, and otherwise report `NOT A GATE`
(or `SMOKE (synthetic)` when `--allow-synthetic` is given). A manifest that mixes synthetic clips
into a gate set is an error. **Why.** The gate exists to show the method works on real speech
(spec §9, §13); a PASS from synthetic clips would be a false one. **Cost if wrong.** None: a
synthetic smoke run is still possible and is labelled as such.

### R53: SwiftF0's weights are unverified

**Decision.** In `data-register.csv` (and its research copy), SwiftF0's `shipped_weights_training`
is `verify`, with the note that the training data's licences (the `swift-f0-training` repository)
are unchecked and must be cleared before the weights ship (spec §11.2). The code licence stays
`allow` (MIT). **Why.** The model's own licence does not cover the data it was trained on.
**Cost if wrong.** None: the row is conservative.

## Platform, trust boundary and limits

### R10: What cannot be verified on Linux

**Decision.** Everything up to the macOS-only steps is built and tested on Linux: `tonekit-ffi`
compiles for the host, the Swift bindings generate, and the build script and Swift tests are
written. They are not run there; the iOS Simulator run is done on a Mac from
[`ios-verification.md`](ios-verification.md). **Why.** iOS-first is the top priority, so the gap is
stated plainly instead of hidden. **Cost if wrong.** An iOS-only build problem surfaces later on
the Mac.

### R43: External pitch tracks are untrusted

**Decision.** In the facade's `analyze`, an externally supplied f0 track is sanitised before use:
a frame whose `hz` is non-finite or not positive becomes unvoiced, and a non-finite `voiced_p`
becomes 0, then every `voiced_p` is clamped to [0, 1]. **Why.** The FFI is a trust boundary: Swift
or Python can hand over any floats, and a NaN frame would otherwise count as voiced when nuclei and
boundaries are found. **Cost if wrong.** None: a non-positive pitch was never valid.

### R52: Input length cap now, faster pYIN later

**Decision.** `analyze` refuses input longer than 30 seconds with `AssessError::TooLong`. A banded
Viterbi pYIN (vendoring pyin's MIT code with a cached transition matrix) is the first task of P1.
P0 measures a 3-second utterance in the Swift latency test. **Why.** pYIN's dense Viterbi is about
four times over the latency budget on a server core and its memory is unbounded (about 500 MB at 120
seconds), which can kill an iOS app; P0's latency is informational. **Cost if wrong.** The Mac run
shows latency well over budget, which is expected until P1.

## Process

One line each; these rulings shaped the workflow, not the library.

- **R6, R15:** Tasks that shared a file ran one after the other, and independent ones ran in
  parallel in their own git worktrees and branches.
- **R13, R18, R29:** Work that an interrupted session left behind unreviewed was redone from the
  written task description, keeping only what met it, rather than trusted as it stood.
- **R31, R45, R49:** Work proceeds one task at a time, on its own branch, split into units that
  commit after each green group of tests with a progress note, so an interruption costs minutes and
  a unit resumes from its branch.
- **R40:** Commit trailers keep each author's own model attribution; history is not rewritten.
- **R54:** The final fix wave was split into two lanes that touch disjoint files and run in
  parallel: decoder and Rust robustness in one, harness, registers, CI and documentation in the
  other, followed by one scoped re-review over both.
- **R57:** The last review findings were fixed in one batch checked by the full gates and a reading
  of the diff, not by another review round.
