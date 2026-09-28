# Tone assessment (`tonekit`): design spec

**Status:** v2.1. DJ approved v1 with changes, then approved v2 with three clarifications
(2026-09-28): iOS-native first with no wasm target, and imprint = the user's own voice. P0 plan
approved for subagent-driven execution. v2.2: DJ confirmed AISHELL-1/3 and THCHS-30 are now plain
Apache-2.0 (the academic-use caveat was rescinded), so they're back in.
**Date:** 2026-09-28
**Superpowers path:** Architectural (new subsystem with a new cross-project interface)
**Research:** `docs/research/2026-09-28-tone-assessment-prior-art.md`, `docs/research/tone-assessment-license-register.csv`
**Consumers:** Bendy Phase 2 (voice, `pinyinRecall`, accent training later), proj-xiuzhen P0 Gate 1 (cast gate)
**Supersedes:** the f0 / `ToneTemplate` / Azure sections of xiuzhen `02-specs/prosody-scoring.md` (see §17)

### What changed from v1

| DJ change | Where it landed |
|---|---|
| Rust is fine; iOS-first, on-device without issue (v2.1: wasm dropped as a target) | §4.3: native `staticlib` on iOS via UniFFI; P0 verifies it on the iOS Simulator; device latency is a P1 gate |
| "Free for academic use" ≠ Bendy, and OSS doesn't launder it | §11.2: the principle stands for any academic-only source. **v2.2:** AISHELL-1/3 and THCHS-30 dropped the caveat and are plain Apache-2.0, so they're allowed. AISHELL-3 is the primary native calibration source |
| Name stays `tonekit`; public after P0; Tencent offline | §16, recorded |
| T1. Role in an ensemble; consumers that self-correct misleading transcripts | §8: a likelihood lattice plus candidate rescoring, with separate priors. Plug-in points named |
| T2. Test TTS models in a GAN framework | §9: adversarial *search* over controlled resynthesis instead of a literal GAN; tonekit also works as a TTS tone critic |
| T3. Accents (and imprints) belong in the pack and grading schema | §6: accent profiles with mixture realisations and per-speaker style profiles. §11.4: voice-likeness constraints |
| T4. A known syllable count is a bad assumption | §7: candidate-set decoding (closed set) plus an open tone lattice. "One intended target" is just a candidate set of size 1 |

---

## 1. Understanding

**What DJ said**
- One audio-input component detects tone from f0, and Bendy and xiuzhen both need it.
  Mandarin now, more languages later.
- Code license: dual MIT/Apache-2.0 unless there's a material concern.
- Rust core. iOS-first: the model must run on-device without issue. Native is preferred; wasm is
  not a goal.
- Accent training is a Bendy goal (post-MVP). Earlier prototypes matched a learner to a
  public-figure "imprint" from the region they want to sound native to, and TTS should lean
  toward that imprint instead of stock characters. Accents are part of the pack and grading
  schema, not an accept-list.
- xiuzhen casts from a growing vocabulary with tonal overlap, and generation will widen it. The
  model must not hard-code a known syllable count.
- tonekit should be a good ensemble member, including for consumers that auto-correct misleading
  transcripts.
- DJ can collect live speaker audio and wants synthetic and adversarial testing as well.

**Carried forward**
- On-device gate, cloud audit only. Score is a distance, not a classification. Targets are
  sandhi-applied, DJ-audited spoken forms. Confusion sets are audited. Whisper mode means "tone
  not checked". (xiuzhen)
- Lexical accent differences live in Bendy's lexicon (`Reading.scope`). Lects are siblings keyed
  by ISO 639-3. (feat-variants)

**Assumptions**
- A1. Learner audio never leaves the device at runtime.
- A2. tonekit is its own repo. Bendy-specific adapters stay in Bendy.

**Success criteria**
- S1. xiuzhen Gate 1: ≥90% correct-accept and ≤10% wrong-accept on the 20-pair corpus, café
  noise, arm's length. The threshold is chosen by leave-one-pair-out.
- S2. A new *accent* (`cmn-TW`) and a new *lect* (`yue`) can each be added as data only.
- S3. Every shipped weights or calibration file traces to sources cleared for commercial use,
  enforced in CI.
- S4. No component assumes the number of syllables spoken.

---

## 2. Decisions

| Question | Decision | Overturned if |
|---|---|---|
| All-in-one model | **No** as a model. **Yes** as an API: `analyze` once, then query | A permissive L2 corpus with per-syllable tone labels exceeding ~100 h appears |
| Generic model returning grades | **Split it.** Measurement is generic; grading is per lect *and accent* | The P2 generality gate fails in a way that points at measurement |
| Per-language input models | **Yes, kept thin:** packs are data (inventory, accents, realisation mixtures, tolerances) plus a small calibration file | Template packs plateau below the P2 gate |
| Per-language output models | **No.** Output is audited native clips, or the learner's own voice resynthesised to the target or imprint contour (DSP) | Own-voice playback tests badly |
| MoE | **No.** The route (lect + accent) is known up front; packs are the hard-routed heads | — |
| Ensemble | **Yes, heterogeneous.** tonekit publishes calibrated **likelihoods** with priors kept separate, so any consumer can fuse without double-counting (§8) | Fusion doesn't beat acoustic-only by ≥3 pts F1 on held-out L2 data |
| Known syllable count | **Removed.** Closed-set decoding over candidate sequences of any length, plus an open lattice (§7) | — |
| Accents | **In the pack:** base accent + accent profiles with weighted realisation mixtures; lexical variants from the caller; optional per-speaker style profile (§6) | — |
| GAN-style testing | **Adversarial search** over controlled WORLD resynthesis, plus tonekit as a TTS critic. No literal GAN (§9) | tonekit gains a differentiable neural evidence source (P3); adversarial training of *that* model is then reasonable |
| License | **Code: MIT OR Apache-2.0.** Weights and data on a separate CI-gated track. UniFFI (MPL-2.0) allowed as a named exception | An FTO search finds a live patent on the method |
| Language | **Rust core.** UniFFI → Swift (native iOS), PyO3 → Python (harness). No wasm target | UniFFI/XCFramework plumbing costs more than 2 days in P0 |
| Generality proof | `cmn-TW` accent (Common Voice zh-TW, CC0), then `yue` lect (Common Voice yue) | — |

The reasoning against an end-to-end grader and against a universal "f0 → grade" model is
unchanged from v1 and summarised in the research doc (§0, §3.2, §4). In short: the L2 data is
tiny (LATIC 4 h; the best published L2 tone-error precision is 0.111), end-to-end models follow
transcripts, a logit can't say "start higher", and tone categories and their phonetics differ by
lect.

---

## 3. Approaches considered

Unchanged from v1. **C. Shared measurement → per-lect/accent pack → evidence fusion** is the
recommendation. v2 adds a decoding layer between measurement and grading, because grading needs
to know *which* syllables were said before it can judge them.

---

## 4. Architecture

### 4.1 Analyse once, query many

```
 PCM 16 kHz mono
   │
   ▼
 analyze() ─────────────────────────────────────────────── Analysis (plain data)
   f0:        F0Provider (pYIN default | External track, e.g. SwiftF0 via CoreML)
   energy:    RMS dB, 10 ms hop
   nuclei:    syllable-nucleus candidates (energy peaks that are voiced)
   boundaries: candidate syllable boundaries (energy minima, voicing edges)
   register:  given | cold-start estimate;  issues: clipping, low SNR, cold start
   │
   ├── decode(analysis, pack, grading, candidates[])      closed set, any lengths
   │        → ranked CandidateScore { llr, posterior, per-syllable fit }
   │
   ├── lattice(analysis, pack, grading)                    open set, no candidates
   │        → ToneLattice: TBU spans × inventory log-likelihoods + posteriors
   │
   └── assess(analysis, pack, grading, intended, distractors, evidence, compare_accents)
            = decode([intended] ∪ distractors) + diagnostics + fusion
            → UtteranceAssessment (xiuzhen/Bendy grading)
```

`tonekit` holds no policy. It reports likelihoods, probabilities, distances and diagnostics.
Thresholds, mastery scaling and UI are the consumer's.

### 4.2 Repository layout

```
tonekit/                               MIT OR Apache-2.0
  crates/
    tonekit-core/     plain types (ids, signal, targets, shape, lattice, evidence, analysis)
    tonekit-testkit/  deterministic synthetic voiced-audio generator (dev-dependency only)
    tonekit-f0/       F0Provider, pYIN provider (`pyin` crate), energy, octave repair, SNR/clipping
    tonekit-segment/  speech region, syllable nuclei, boundary candidates
    tonekit-shape/    Register, Chao normalisation, ToneShape extraction, StyleProfile fitting
    tonekit-pack/     pack TOML schema (lect + accents), expectations, likelihoods, deltas
    tonekit-decode/   closed-set segmental DP, open lattice (forward–backward)
    tonekit-fuse/     evidence fusion, assessment assembly
    tonekit/          facade: analyze / decode / lattice / assess
    tonekit-cli/      `tonekit` binary for quick local checks on WAV files
    tonekit-ffi/      UniFFI → Swift XCFramework
    tonekit-py/       PyO3 → Python (harness)
  packs/cmn/          cmn.toml, cmn.calib.json, PROVENANCE.toml
  harness/            Python (uv): manifest, eval, synth/adversarial, bakeoff, provenance
  fixtures/           synthetic + owned audio, expected JSON
  deny.toml  LICENSE-MIT  LICENSE-APACHE  MODEL_CARD.md  DATA_PROVENANCE.md
```

### 4.3 Target: native iOS, on-device

- **Production:** `aarch64-apple-ios` / `aarch64-apple-ios-sim` static library via UniFFI →
  XCFramework. There's no network, no web view and no interpreter: the same compiled code the
  tests exercise runs on the phone.
- **Verification:** P0 runs the Swift test suite on the iOS Simulator (plan Task 12). P1 gates
  p95 latency on a physical iPhone 12.
- **No wasm target (DJ, v2.1).** Core crates stay pure functions (no threads, filesystem, clock or
  randomness) because that keeps them deterministic, testable and embeddable, not for wasm. The
  `pyin` crate is used with default features off (ndarray + rustfft only).

---

## 5. Core types

Pinned first in `tonekit-core`. Every other crate builds against these in parallel. All types
derive `Clone, Debug, PartialEq, Serialize, Deserialize`, plus UniFFI derives behind the `ffi`
feature.

```rust
// ids.rs: newtypes over String
pub struct Lect(pub String);        // ISO 639-3: "cmn", "yue"
pub struct AccentId(pub String);    // "cmn-standard", "cmn-TW"
pub struct ToneId(pub String);      // pack-scoped; cmn "1".."5" == Bendy Tone raw values
pub struct CandidateId(pub String);

// signal.rs
pub const SAMPLE_RATE: u32 = 16_000;
pub const HOP: usize = 160;                           // 10 ms
pub struct F0Frame { pub hz: Option<f32>, pub voiced_p: f32 }
pub struct F0Track { pub frames: Vec<F0Frame>, pub provider: String }   // frame i at i*10 ms
pub struct EnergyTrack { pub db: Vec<f32> }
// Frame indices are u32 everywhere (UniFFI has no usize or tuples).
pub struct FrameRange { pub start: u32, pub end: u32 }                  // [start, end)
pub struct Nucleus { pub frame: u32, pub strength_db: f32 }

// target.rs
pub struct WeightedTone { pub tone: ToneId, pub weight: f32 }
/// One syllable the speaker may have said. `lexical_variants` carries within-accent lexical
/// alternatives from the caller's lexicon (星期 xīngqī / xīngqí); weights sum to < 1 and the
/// main tone takes the remainder.
pub struct ToneTarget { pub tone: ToneId, pub lexical_variants: Vec<WeightedTone>, pub label: Option<String> }
pub struct Candidate { pub id: CandidateId, pub targets: Vec<ToneTarget> }
pub struct GradingTarget { pub accent: AccentId, pub style: Option<StyleProfile>, pub style_weight: f32 }

// register.rs: semitones re 55 Hz; four numbers, deliberately coarse (§11.3)
pub struct Register { pub floor_st: f32, pub median_st: f32, pub ceil_st: f32, pub n_syllables: u32 }

// style.rs: an individual's realisation within an accent (imprint). No timbre, no embedding.
pub struct StyleTone { pub tone: ToneId, pub contour: Vec<f32>, pub n: u32 }
pub struct StyleProfile { pub accent: AccentId, pub tones: Vec<StyleTone>, pub mean_range: f32 } // Chao units

// shape.rs
pub const CONTOUR_POINTS: usize = 10;
pub struct TbuSpan { pub start_frame: u32, pub end_frame: u32 }         // [start, end)
pub struct ToneShape {
    pub span: TbuSpan,
    /// Chao scale: 1 + 4·(st − floor)/(ceil − floor), unclamped; CONTOUR_POINTS long.
    pub contour: Vec<f32>,
    /// Per-point fraction of voiced frames behind each contour point (0..1).
    pub voiced_weights: Vec<f32>,
    pub onset: f32, pub offset: f32, pub mean: f32,
    pub slope: f32, pub curvature: f32, pub turning_point: Option<f32>, pub range: f32,
    pub duration_ms: f32, pub voiced_fraction: f32, pub f0_confidence: f32,
    pub phonation: Option<Phonation>,          // reserved; None until a pack declares it
}
pub struct Phonation { pub creak_ratio: f32, pub cpp_db: f32 }

// judgement.rs
pub enum MeasureIssue { Unvoiced, LowSnr, Clipped, TooShort, ColdStartRegister }
pub enum Measured { Full, Partial { issues: Vec<MeasureIssue> }, NotMeasured { issue: MeasureIssue } }
/// Advice direction ("start higher"). `amount` is in Chao units, or ms for Turn*.
pub enum DeltaKind { StartHigher, StartLower, EndHigher, EndLower, TurnEarlier, TurnLater, WiderRange, NarrowerRange }
pub struct ShapeDelta { pub kind: DeltaKind, pub amount: f32 }
pub struct ToneJudgement {
    pub expected: ToneId,
    pub loglik: Vec<f32>,          // calibrated, per inventory tone, in context
    pub llr_target: f32,           // log p(shape | target mixture) − log p(shape | background)
    pub distance: Option<f32>,     // to best-matching target component (xiuzhen contourDistance)
    pub component: Option<String>, // which realisation matched, e.g. "cmn-TW/t3-low"
    pub heard: Option<ToneId>,
    pub deltas: Vec<ShapeDelta>,
    pub measured: Measured,
}

// lattice.rs: the ensemble interface (§8)
pub struct LatticeTbu { pub span: TbuSpan, pub loglik: Vec<f32>, pub posterior: Vec<f32>,
                        pub measured: Measured, pub shape: Option<ToneShape> }
pub struct ToneLattice { pub schema: String, pub lect: Lect, pub accent: AccentId,
                         pub inventory: Vec<ToneId>, pub prior: Vec<f32>, pub tbus: Vec<LatticeTbu> }

// decode.rs
pub struct SyllableFit { pub span: TbuSpan, pub judgement: ToneJudgement }
pub struct CandidateScore { pub id: CandidateId, pub llr: f32, pub posterior: f32, pub syllables: Vec<SyllableFit> }
/// `candidates` sorted by llr desc; posteriors are shares of a softmax that also includes the
/// null competitor (`null_llr + null_bias`), whose share is `null_posterior`.
pub struct DecodeResult { pub candidates: Vec<CandidateScore>, pub null_llr: f32, pub null_posterior: f32 }

// evidence.rs / fusion.rs
pub struct ConfusionHit { pub tone: ToneId, pub text: String }
pub enum Evidence { Acoustic { judgement: ToneJudgement },
                    Transcript { matched_target: bool, confusion_hit: Option<ConfusionHit> },
                    Neural { p_correct: f32, model: String } }   // P(target tone produced) from a neural model
pub enum EvidenceKind { Acoustic, Transcript, Neural }
pub struct FusionWeights { pub beta0: f32, pub beta_acoustic: f32, pub beta_transcript: f32,
                           pub beta_neural: f32, pub veto_cap: f32 }
pub struct SyllableAssessment { pub expected: ToneId, pub p_correct: f32, pub distance: Option<f32>,
    pub heard: Option<ToneId>, pub heard_as: Option<String>, pub deltas: Vec<ShapeDelta>,
    pub component: Option<String>, pub measured: Measured, pub basis: Vec<EvidenceKind> }
pub struct AccentFit { pub accent: AccentId, pub llr: f32 }
pub struct UtteranceAssessment { pub schema: String, pub intended: CandidateId, pub intended_rank: u32,
    pub margin_llr: f32,   // intended llr − max(best other candidate llr, null_llr)
    pub syllables: Vec<SyllableAssessment>,
    pub overall: Option<f32>,          // None when no syllable has tone evidence ("tone not checked")
    pub accent_fit: Vec<AccentFit>, pub register_update: Register }

// analysis.rs
pub enum RegisterSource { Given, ColdStart }
pub struct Analysis { pub f0: F0Track, pub energy: EnergyTrack, pub nuclei: Vec<Nucleus>,
    pub boundaries: Vec<u32>, pub speech: Option<FrameRange>, pub register: Register,
    pub register_source: RegisterSource, pub voiced_st: Vec<f32>, pub issues: Vec<MeasureIssue> }
```

**Bendy adapter mapping (P1, in Bendy):** `SyllableAssessment` → `SyllableScore` (`expected`
from `Tone(rawValue:)`, `observedTone` ← `heard`, `contourDistance` ← `distance`).
`hitToneConfusion` = any `Transcript` evidence with a hit. `ToneDiagnostic.heardAs` ←
`heard_as`. The cmn ids match Bendy's `Tone` raw values, so fixtures migrate by adding
`lect: "cmn"` when Bendy's second lect arrives.

---

## 6. Language packs, accents and imprints

### 6.1 Three layers of variation, three owners

| Layer | Example | Owner | Mechanism |
|---|---|---|---|
| **Lexical:** which tone a word carries in this accent | TW reads many Beijing neutral tones as full tones; 星期 xīngqī/xīngqí; 垃圾 lājī/lèsè | Bendy lexicon (`Reading.scope`) | Caller resolves targets for the chosen accent; within-accent alternatives go in `ToneTarget.lexical_variants` with weights |
| **Realisational:** how a tone surfaces in this accent | TW T3 as low-falling 21 even phrase-finally; neutral-tone pitch pattern; range | tonekit pack `[[accent]]` | Weighted **mixture** of realisations. Likelihood is the log-sum over components, so native-typical variants are credited in proportion to how typical they are, not accepted flat |
| **Individual style (imprint):** how one speaker realises tones within an accent | an imprint speaker's T2 rises later and wider | Consumer (Bendy) | `StyleProfile` blended into expectations by `style_weight`; fitted with `tonekit-shape::fit_style` |

Packs are data. Anything that needs code becomes a named core **capability** (`register` in P0;
`declination`, `phonation`, `mora` when their first lect is scheduled). Fields for these are
reserved now so the FFI stays stable.

### 6.2 `cmn.toml` (seed values; fitted in P1)

```toml
[pack]
lect = "cmn"
version = "0.2.0"
tbu = "syllable"
capabilities = ["register"]
base_accent = "cmn-standard"
heard_threshold = 0.6
prior = { "1" = 0.22, "2" = 0.22, "3" = 0.16, "4" = 0.30, "5" = 0.10 }

[[tone]]
id = "1"
name = "阴平 high level"
chao = [5, 5]

[[tone]]
id = "2"
name = "阳平 rising"
chao = [3, 5]

[[tone]]
id = "3"
name = "上声 dipping"
chao = [2, 1, 4]

[[tone]]
id = "4"
name = "去声 falling"
chao = [5, 1]

[[tone]]
id = "5"
name = "轻声 neutral"
chao = "context"

[tolerance]
contour = 0.7
onset = 0.8
offset = 0.8
turning_point = 0.2

[[unvoiced_ok]]
tone = "3"
region = [0.3, 0.8]

[confusions]
pairs = [["2", "3"], ["1", "4"], ["1", "2"]]

# ---- base accent: Putonghua standard --------------------------------------------------
[[accent]]
id = "cmn-standard"
name = "普通话 (standard)"

[[accent.realize]]
label = "t3-half"
when = { tone = "3", phrase_final = false }
chao = [2, 1]

[[accent.realize]]
label = "t5-after-1"
when = { tone = "5", prev = "1" }
chao = [2]

[[accent.realize]]
label = "t5-after-2"
when = { tone = "5", prev = "2" }
chao = [3]

[[accent.realize]]
label = "t5-after-3"
when = { tone = "5", prev = "3" }
chao = [4]

[[accent.realize]]
label = "t5-after-4"
when = { tone = "5", prev = "4" }
chao = [1]

# Fallback for a neutral tone with no previous syllable (rare; keeps every context resolvable).
[[accent.realize]]
label = "t5-default"
when = { tone = "5" }
chao = [3]

# Phrase-final T3 is often produced without the full rise even in the standard.
[[accent.realize]]
label = "t3-final-dip"
when = { tone = "3", phrase_final = true }
mixture = [ { chao = [2, 1, 4], weight = 0.6 }, { chao = [2, 1], weight = 0.4 } ]

# ---- Taiwan Mandarin (國語). Realisational differences only; lexical ones come from Bendy.
[[accent]]
id = "cmn-TW"
name = "國語 (Taiwan)"
inherits = "cmn-standard"

[[accent.realize]]
label = "t3-low"
when = { tone = "3" }
mixture = [ { chao = [2, 1], weight = 0.8 }, { chao = [2, 1, 3], weight = 0.2 } ]

[accent.tolerance]
contour = 0.8
```

**Resolution order** for `expect(grading, target, ctx)`: take the most specific matching
`realize` rule in the chosen accent. Specificity is the number of `when` keys; ties go to the
first in file order. If none matches, walk `inherits`. If none matches there, use
the citation `chao`. A tone whose citation is `"context"` with no matching rule is a
`PackError::MissingRealization`, caught at pack load by enumerating every context.

### 6.3 Grading against accent and imprint

- **Target expectation** = Σ over lexical variants (weight) × Σ over realisation components
  (weight), as a Gaussian mixture in feature space. With a `StyleProfile` whose tone has n ≥ 5
  observations, each component's contour is blended:
  `(1 − style_weight)·accent + style_weight·style`.
- **`accent_fit`** is computed *only for accents the caller lists* in `compare_accents`: the
  intended candidate is re-decoded under each accent and the LLR reported. This is what accent
  training needs ("your T3 fits 國語 better than 普通话"). There is deliberately no API that
  identifies an accent across all profiles (§11.5).
- **`fit_style(fits) -> StyleProfile`** takes `SyllableFit`s from decoded clips of one speaker
  (for example, clips a learner picked from their imprint's public media) and produces per-tone
  mean contours in *that speaker's* normalised Chao space. That's the only form an imprint takes
  inside tonekit.

### 6.4 Future lect sketches (schema checks, not builds)

- **yue:** tones `55, 25, 33, 21, 23, 22`, with entering tones as short variants. Tolerance
  weights height over shape.
- **tha:** `m 33, l 21, f 51, h 45, r 14`, with ids from PyThaiNLP `tone_detector`.
- **vie:** declares `phonation`.
- **yor:** declares `declination`.
- **jpn:** `tbu = "mora"`, tones `H`/`L`.

---

## 7. Decoding and scoring

### 7.1 Syllable-level likelihood (pack)

For a `ToneShape` x and an expectation component c with tolerance σ (widened ×1.5 when the
analysis has `LowSnr`, `Clipped` or `ColdStartRegister`):

```
d²(x,c) = WRMS(x.contour − c.contour; w)² / σ_c²  +  0.5·(x.onset − c.onset)²/σ_on²  +  0.5·(x.offset − c.offset)²/σ_off²
log p(x | c) = −½·d² − ln(σ_c·σ_on·σ_off)
w_k = max(x.voiced_weights[k], 0.25), except inside the pack's unvoiced_ok region for c's tone,
      where points with voiced_weights[k] < 0.5 get w_k = 0   (T3 creak is not evidence against T3)
```

- Mixture: `log p(x | tone t, ctx) = logsumexp_c(ln w_c + log p(x|c))`.
- Background: `log p_bg(x) = logsumexp_t(ln prior_t + log p(x | t, ctx))`.
- **LLR** for a target = `log p(x | target mixture) − log p_bg(x)`. It's ≈0 for an uninformative
  shape, positive for a good match and negative for a mismatch. Candidates of different lengths
  are comparable because every syllable contributes evidence *relative to a background*.
- Calibration: all logliks are divided by a per-pack temperature T (`cmn.calib.json`), fitted in
  P1. Seed T = 1.
- `heard` = argmax of the posterior (prior × calibrated likelihood) if it's ≥ `heard_threshold`.
- `distance` = √d² to the best target component; `component` names it.
- Deltas: onset, offset, turning-point time and range differences to the best component. Emit
  the two largest above 1σ. Under `TooShort` only onset/offset deltas are emitted, and under
  `LowSnr` none are, so advice never comes from a contour the scorer distrusts.

### 7.2 Closed-set decoding (any syllable count)

Inputs: boundary candidates B (sorted frames), speech region, candidates of any lengths.

- **Segment cache:** a ToneShape for each boundary pair (b_i, b_j) spanning 60–800 ms (a
  `MeasureIssue` if unvoiced or too short).
- **Per candidate with K targets,** a DP over (boundary index, syllables consumed):
  - A *syllable* edge (b_i → b_j, target k) scores `LLR(shape_ij, target_k, ctx_k) + dur(b_j − b_i)`.
    Here `ctx_k` = previous *target* tone, index, count, and `phrase_final = (k = K−1)`.
  - A *gap* edge (b_i → b_j) costs `filler_per_frame × speech frames in (b_i, b_j)`, while
    silent frames are free. This covers hesitations, restarts and extra words.
  - Paths start at any boundary with leading speech frames charged as filler, and end the same
    way.
  - An unmeasurable syllable scores `unvoiced_syllable_llr`.
- `dur(d) = logN(d; ln r, 0.4) − logN(r; ln r, 0.4)`, where r = median inter-nucleus interval
  (default 220 ms).
- **Null hypothesis ("something else was said"):**
  `null_llr = Σ_tbu [max_t loglik_t − logsumexp_t(ln prior_t + loglik_t)]` over the open lattice
  (§7.3). That is the best free choice of tone per nucleus, which is always ≥ 0. Candidate
  posteriors are a softmax over `{llr_c} ∪ {null_llr + null_bias}`.
- Seeds live in `cmn.calib.json`: `filler_per_frame = 0.03`, `unvoiced_syllable_llr = −3.0`,
  `null_bias = −2.0`.
- Cost is O(|B|²·K) per candidate. With |B| ≤ 4·nuclei + 2 and up to 64 candidates, this is
  microseconds to milliseconds.

This subsumes v1's "known N": a single intended candidate is a set of size 1, and the same code
handles spellbooks with tonal overlap, extra syllables and a generation-widened vocabulary.

### 7.3 Open lattice (no candidates)

- TBUs = one per nucleus, bounded by the nearest boundary candidates on either side.
- Forward–backward over tone sequences with state = (previous tone, current tone), so
  context-dependent realisations like the neutral tone and the half-third are handled.
  Transitions come from the pack unigram prior (bigram in P1). Emissions are calibrated
  likelihoods.
- Output per TBU: context-marginalised `loglik[t]`, `posterior[t]`, `measured`, and the shape.

### 7.4 Fusion (for `assess`)

`logit(p_correct) = β0 + β_ac·llr_target + β_tr·x_tr + β_nn·logit(p_nn)`. A syllable with no
contributing evidence gets `p_correct = sigmoid(β0)` and an empty `basis`.

- `x_tr` = +1 if the transcript matched the target, otherwise 0.
- A confusion hit caps `p_correct` at `veto_cap` (0.05).
- Missing evidence drops its term.
- P0 seeds: β0 = 0, β_ac = 1, β_tr = 0.5. Fitted per lect in P1.
- `overall` = the minimum `p_correct` over syllables that were measured **or** carry a confusion
  hit, since one wrong tone fails a cast. A whispered confusion hit is a miss, not "not checked".
  It's `None` only if no syllable has either kind of tone evidence.

---

## 8. tonekit as an ensemble member

**The problem DJ named:** a recognizer hears 睡 shuì, its language model writes 水, and the
transcript misleads. A consumer that wants to *self-correct* needs acoustic tone evidence in a
form it can combine with its own scores.

**What tonekit publishes, and why each property matters**

| Output | Property | Why a fusing consumer needs it |
|---|---|---|
| `ToneLattice.loglik` | calibrated **likelihoods**, per TBU × tone | Fusing posteriors double-counts priors. Likelihoods can be combined with any LM or ASR score |
| `ToneLattice.prior` | separate from likelihoods | Consumers with their own language model drop it; consumers without one use it |
| `TbuSpan` (10 ms frames) | time-aligned | Maps onto recognizer segment timestamps |
| `Measured` per TBU | explicit abstention | "Tone not measured" must not be read as "tone wrong" |
| `decode()` over consumer candidates | per-candidate LLR, comparable across lengths | Direct **n-best rescoring**: `score = asr_logprob + λ·tonal_llr` |
| `schema` version string | `tonekit.lattice.v1`, `tonekit.assessment.v1` | Stable JSON for LLM prompts and cross-language consumers |

**Plug-in points (ordered by cost)**

1. **Apple Speech n-best (P1).** `SFSpeechRecognitionResult.transcriptions` (ranked alternatives)
   and per-segment `alternativeSubstrings` feed candidates: Bendy converts each alternative to
   toned pinyin via its lexicon, calls `decode()`, and reranks. That produces two transcripts:
   **faithful** (acoustics weighted high, what the learner said: "you said 睡 shuì") and
   **intent** (the recognizer's own guess, what they meant). Both are useful, and the UI shows
   the gap.
2. **LLM consumer (P1/P2).** A compact serialisation of the lattice (top-2 tones with
   probabilities, discretised height and contour, measured flags) goes to the Claude or
   OpenRouter fallback that Bendy already uses. CantoASR is published prior art for this
   descriptor-to-LLM pattern in Cantonese (−23% relative CER). `to_prompt_json` ships in the P1
   plan.
3. **Open-source decoder shallow fusion (P3).** sherpa-onnx (Apache-2.0, iOS examples) with
   tonekit as a scorer during beam search. Only worth it if post-hoc rescoring leaves errors on
   the table.
4. **Tone-only neighbours.** Generating confusion candidates is the consumer's job, since it
   requires a lexicon. tonekit ranks them.

The λ in `asr_logprob + λ·tonal_llr` is fitted per lect in the harness. Expected calibration
error of the lattice is a tracked metric from P1 on.

---

## 9. Synthetic and adversarial testing

**Short answer to "can we test TTS models in a GAN framework?"** Yes to the adversarial part, no
to a literal GAN.

- **Why not a literal GAN.** GAN training needs a differentiable discriminator, and tonekit is
  deliberately DSP + DP + small calibration. Making it trainable end-to-end rebuilds the opaque
  grader §2 rejects. A trained generator also adds little over parametric resynthesis whose
  labels we control exactly.
- **What we do instead: adversarial search.**
  1. **Controlled resynthesis.** WORLD (modified-BSD) via pyworld (MIT) analyses owned or CC0
     recordings into f0, spectral envelope and aperiodicity. We replace f0 with a target contour
     rendered in the speaker's own register and resynthesise. The timbre stays real, and the
     tone and f0 ground truth are exact.
  2. **Perturbation families modelled on L2 error literature:** whole-tone substitution; range
     compression (×0.4–0.8); turning-point shift (±40–120 ms); onset or offset shift (±0.5–1.5
     Chao); T3 without dip or with a full dip; neutral tone given full tone. Nuisance factors:
     café noise at 5/10/20 dB, creak insertion, register shift (±6 st) and rate (0.8–1.25×).
  3. **Search.** A black-box optimiser (random search in P0; CMA-ES in P1) over perturbation
     parameters maximises tonekit's error: wrong-tone variants it accepts, correct variants it
     rejects. The search is constrained to realistic magnitudes (within native variability
     measured on Common Voice).
  4. **Human in the loop.** The search finds cases at the true perceptual boundary, where the
     "label" is itself ambiguous. DJ listens to every adversarial find before it becomes a
     fixture or moves a threshold.
- **TTS in the loop, two directions.**
  - *As a generator of test audio.* Apple system voices (zh-CN, zh-TW, zh-HK) on macOS give
    accent coverage for fixtures. Open TTS with tone-controllable input only after a register row
    clears its weights, since many are trained on non-commercial data.
  - *As something tonekit grades (critic).* `tkh critic` checks that TTS output carries the
    intended tones for the chosen accent, the way DunDun does for Yorùbá TTS. That's needed
    before any generated reference audio reaches learners, and for the imprint-style output in
    §6.3.
- **Provenance.** Synthetic audio inherits its generator's and source clip's provenance.
  **Synthetic or TTS audio is used for tests and diagnostics, never for fitting shipped
  calibration,** and gates are always measured on real recordings. The synthetic-to-real gap
  (canonical tones, clean spectra) is exactly why.

---

## 10. Runtime

- Input: 16 kHz mono f32. Other rates return `AssessError::UnsupportedSampleRate`; the caller
  resamples.
- pYIN: 10 ms hop, 1024-sample frame, 50–600 Hz.
- Budget: `analyze + assess` with ≤16 candidates, p95 ≤100 ms for a 3 s utterance on iPhone 12.
  Stripped static library ≤2 MB without SwiftF0.
- **No networking code in any crate.** `deny.toml` bans HTTP/TLS crates.
- **Register:**
  - Per utterance, take the 5th/50th/95th percentiles of voiced semitones. Merge with weight
    `w = min(0.5, u/(n+u))`, where u = syllables this utterance and n = syllables so far.
  - Cold start (no register given): use utterance percentiles widened by ±2 st, and flag
    `ColdStartRegister` until n ≥ 30.
  - Bendy persists it per user; an optional 妈麻马骂 onboarding utterance seeds it.
  - It's never inferred from anything but the user's own f0.

---

## 11. Licensing, provenance, privacy, safety

### 11.1 Code

MIT OR Apache-2.0. DCO sign-off for contributions. `deny.toml` allows MIT, Apache-2.0,
BSD-2/3-Clause, ISC, Zlib and Unicode-3.0, plus **MPL-2.0 for `uniffi*` crates only** (UniFFI is
MPL-2.0; file-level copyleft, used unmodified). It denies GPL, LGPL, AGPL and SSPL. The one
tone-feature patent found (US6829578B1) expired in 2022. Schedule an FTO search before a funded
launch.

### 11.2 Data: DJ's question on "free for academic use"

DJ's reading is right on both counts. This is a factual analysis, not legal advice, and counsel
should review the register before launch.

1. **Passthrough.** A restriction on a dataset follows what's derived from it. tonekit can't
   grant rights it doesn't have, so MIT/Apache on calibration derived from academic-only data
   would misstate the terms to every downstream user, Bendy included.
2. **Was it ever academic use?** No. Use is judged by who uses it and why. DJ building tonekit to
   power Bendy is commercial use from day one, and open-sourcing the result doesn't change that.

These two points still govern any source whose terms say "academic" or "research" use.

**v2.2 update (DJ, 2026-09-28):** the "free for academic use" caveat on AISHELL-1/3 and THCHS-30
has been rescinded. Both corpora are now plain Apache-2.0, which permits commercial use, so
they're `allow` in the register. When the harness downloads them, it archives the license text
with the download date next to the data, so the provenance claim can be shown later.

- **Calibration path:**
  - **AISHELL-3** (Apache-2.0, 85 h, 218 speakers) is the primary native source. It ships
    toned-pinyin transcripts, so tone targets come from the corpus instead of being generated,
    which removes the main source of label noise. Neutral-tone and sandhi realisations still get
    a DJ audit of a 200-syllable sample, because transcripts can record citation tones.
  - AISHELL-1 and THCHS-30 (Apache-2.0) serve as extra native speakers and held-out evaluation.
  - Common Voice zh-CN (CC0) is a held-out cross-corpus check. Common Voice zh-TW (CC0) fits the
    `cmn-TW` accent, with targets from pypinyin + g2pW + tone-sandhi rules.
  - Spans come from tonekit's own single-candidate decoder, re-estimated over 2–3 EM-style
    passes, with robust statistics (median/MAD).
  - Owned and consented recordings set the L2 operating points. OMPAL and LATIC stay `verify`
    until their terms are confirmed.
- **MFA Mandarin** (CC BY 4.0) stays `verify`: it was also trained on AI-DataTang, whose license
  is still unconfirmed. P0 doesn't need it.
- **CI:** `tkh provenance` fails any weights or calibration manifest listing a `deny` source, or
  a `verify` source without a recorded sign-off.

### 11.3 Voice privacy

- On-device only. PCM is discarded after analysis unless the user saves a clip.
- No speaker embeddings, ever. `Register` is four numbers, and `StyleProfile` is per-tone mean
  contours in normalised space: pitch-shape statistics, not timbre.
- Common Voice's no-re-identification term is honoured.

### 11.4 Imprints and voice likeness: resolved (DJ, v2.1)

**Decision:** Bendy's imprint models **the user's own voice**, with the user's explicit
permission, as a target to aim for. It never replicates a known third party's voice. Voice
modelling is out of scope for tonekit. The background below is kept for the record.

Bendy's imprint idea (match a learner to a public figure, and have TTS lean toward them) runs
into voice-likeness law:

- **Beijing Internet Court (2024).** AI voice synthesis trained on a voice actor's recordings
  infringed her personality rights. The court's identifiability finding cited mimicry of "vocal
  characteristics, **intonation** and pronunciation style". Damages were ¥250,000.
- **Tennessee's ELVIS Act (2024).** Covers simulated voices of living people, and adds liability
  for distributing tools whose primary purpose is producing an identifiable person's voice
  without authorisation.
- **California AB 2602 / AB 1836.** Regulate digital-replica contracts and deceased performers'
  replicas.

**Constraints this spec adopts:**

1. tonekit ships the *mechanism* (`StyleProfile`, `fit_style`) and **no profiles of named
   people**.
2. **Never render a real person's timbre** without that person's written, specific consent.
   Imprint-style output is rendered in the **learner's own voice** (own-voice resynthesis with
   the imprint's contour style) or in a **licensed voice-talent** voice.
3. Public-figure imprints in Bendy are **reference-only**: link out to the public media for the
   learner to mimic, compute a style profile on-device from clips the learner chooses, and never
   host or redistribute the audio.
4. "Which public figure do I sound like" matching uses `Register` only (pitch range). It's a
   product decision that needs legal review before launch, and a licensed-voice-talent imprint
   roster is the lower-risk default.

### 11.5 Misuse boundary

Grading, decoding and `accent_fit` are always relative to **caller-supplied targets and
accents**. tonekit ships no L1, dialect, origin or nativeness identification API or model, and
won't accept one; the README says so. Accent fit over a learner-chosen short list, on the
learner's own audio, on-device, is inside that boundary.

---

## 12. Error handling

| Condition | Detection | Result |
|---|---|---|
| Wrong sample rate / empty audio | input check | `AssessError` |
| No speech | no speech region | every syllable `NotMeasured(Unvoiced)`; `overall = None`; consumer shows "tone not checked" |
| Whisper | voiced fraction < 0.2 in speech region | as above |
| Clipping (>1% samples ≥ 0.99) / low SNR (<10 dB) | analyze | `Partial` issue; σ ×1.5; deltas suppressed under LowSnr |
| Extra, missing or hesitation syllables | decode | absorbed by gap edges / low candidate LLR; never shifts every tone by one |
| Octave jump (>9 st from neighbour median) | f0 post-process | shifted ±12 st toward median |
| T3 creak | unvoiced_ok | not penalised |
| Voiced part < 80 ms | shape | `Partial(TooShort)`; onset/offset terms only |
| Unknown tone / accent / missing realisation | pack | `PackError`, surfaced at load where possible |

---

## 13. Testing and evaluation

- **Unit:** every crate, against `tonekit-testkit` synthetic voiced audio. This is a harmonic
  source following Chao contours with syllable envelopes, noise and seeded jitter, so tests have
  exact f0 ground truth without audio files.
- **Property tests:** pitch-scale invariance of Chao contours (±0.05); time-stretch invariance
  (±0.1); monotonicity (moving a shape toward its expectation never lowers LLR); decoder
  length-robustness (an extra filler syllable doesn't change the winning candidate).
- **Snapshots:** owned and CC0 clips → JSON (insta).
- **Parity:** Rust ↔ Python ↔ Swift equality on fixtures; Swift runs on the iOS Simulator.
- **Harness metrics:**
  - S1 gate (leave-one-pair-out threshold).
  - Candidate-ID accuracy on tone-minimal spell sets.
  - Robustness on count-mismatch clips.
  - f0 bakeoff: gross pitch error and voicing error on WORLD-resynthesised clips with exact
    ground truth.
  - From P1: ECE of lattice posteriors, and native tone-ID on AISHELL-3 held-out speakers as a
    regression floor.
- **Synthetic and adversarial:** §9. Diagnostics only, never gates.

---

## 14. Phases, gates, lanes

The plan for P0 is `docs/superpowers/plans/2026-09-28-tonekit-p0.md`. Later phases get their own
plans.

**P0: feasibility + general decoding.** About three weekends; runs as xiuzhen P0's prosody lane.
- Build every crate in §4.2 at P0 depth. The cmn pack has `cmn-standard` populated and `cmn-TW`
  seeded but not fitted.
- Harness: manifest, eval, WORLD perturbation, random-search adversary, SwiftF0 bakeoff and
  provenance check.
- DJ corpus per the plan's recording protocol.
- **Gate:** S1.
- **Non-gating reports:** candidate-ID accuracy on minimal-pair spell sets, count-mismatch
  robustness, and the bakeoff.
- **Fail path:** add an offline SSL tone classifier as evidence. If it still fails, xiuzhen dies
  per its own gate, and Bendy keeps contour visualisation without grading.

**P1: Bendy Phase 2 voice.**
- `BendyProsody` adapter; register persistence and onboarding.
- AISHELL-3 calibration (EM passes), with a Common Voice zh-CN cross-corpus check; fitted fusion
  and λ.
- Apple n-best rescoring with faithful/intent transcripts; `to_prompt_json`.
- CMA-ES adversary; `tkh critic` for reference audio; DJ-audited diagnostic copy; Tone Lab view.
- **Gate:**
  - ≥6 consented L2 speakers across ≥3 L1s, including English.
  - False alarms ≤10% on DJ-judged-correct syllables.
  - ≥70% detection of DJ-judged tone errors.
  - p95 ≤100 ms on iPhone 12.

**P2: generality proof.**
- Fit `cmn-TW` on Common Voice zh-TW; add `yue` on Common Voice yue.
- **Gate:** no diff outside `packs/` and harness loaders. `yue` native syllable tone-ID ≥70% on
  held-out speakers; `cmn-TW` accent-fit LLR prefers 國語 over 普通话 on ≥75% of zh-TW clips.
- **Diagnosis if it fails:** train a supervised per-lect head on the same descriptors. If that
  head is ≥80%, fix calibration. If it's below 70% too, fix the descriptor schema in core before
  adding anything else.

**P3: optional.**
- Neural evidence source (permissive data only; this is also where adversarial training becomes
  meaningful).
- Own-voice resynthesis playback including imprint style.
- sherpa-onnx shallow fusion; `vie`/`yor`/`jpn` capabilities.

| Lane | Work |
|---|---|
| [CDX] ×5 parallel | core + testkit first, then f0, segment, shape, pack and fuse in parallel; then decode, facade, cli, ffi and py |
| [CUR] + human deep-dive | DSP review (octave repair, creak, nuclei), UniFFI/XCFramework, iOS Simulator CI, on-device profiling |
| [RRK] | Tone Lab view in P1 (contour over expected band, deltas, faithful-vs-intent transcript) |
| [DJ] | Corpus recording, pack/realisation/copy audits, dataset clarification emails, adversarial-find listening |
| [OCW] | README, MODEL_CARD, DATA_PROVENANCE, diagnostic copy drafts |

---

## 15. Out of scope (YAGNI)

- Segmental scoring (stays with the recognizer).
- Per-language TTS or voice-conversion models.
- Rendering any real person's timbre.
- Sentence intonation beyond `declination`.
- Android, web, wasm and server runtimes.
- Online learning from user audio.

---

## 16. Decisions record

| # | Decision | Status |
|---|---|---|
| 1 | Rust core; native iOS via UniFFI | **Decided** (DJ) |
| 2 | Academic- or research-only sources never feed shipped calibration (passthrough; commercial use from day one) | **Decided** (DJ's analysis, §11.2) |
| 3 | Name `tonekit` until it works | **Decided** |
| 4 | Public repo after the P0 gate | **Decided** |
| 5 | Tencent SOE offline on DJ-owned recordings only | **Decided** |
| 6 | Imprint = the user's own voice, with explicit user permission; no third-party voice replication; out of scope for tonekit | **Decided** (DJ, v2.1) |
| 7 | No wasm target; iOS on-device native is the only runtime target | **Decided** (DJ, v2.1) |
| 8 | AISHELL-1/3 and THCHS-30 are plain Apache-2.0 (caveat rescinded) and allowed; AISHELL-3 is the primary native calibration source | **Decided** (DJ, v2.2) |

---

## 17. Changes to existing specs

- **xiuzhen `prosody-scoring.md`:**
  - f0 now points here. "Swift + vDSP" is superseded (§4.3).
  - `ToneTemplate` → `packs/cmn/cmn.toml`.
  - Azure is limited to word/syllable accuracy; Tencent SOE pinyin mode is the tone auditor.
  - "Segmented against a known syllable count" is superseded by candidate-set decoding (§7.2).
    Casting passes the spell plus its tone-overlap neighbours as distractors.
  - The P0 [CDX-B] deliverable becomes the tonekit P0 plan.
- **Bendy `Tone` enum:** unchanged; lect-scoping when the second lect lands.
- **Bendy `AccentProfile`:** tone handling moves out of `admits()` accept-lists into tonekit
  accent profiles (realisational) plus lexicon readings (lexical). `AccentProfile` gains an
  `accent: AccentId` link.
