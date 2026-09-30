# tonekit

Grades lexical tone (Mandarin first) from a short recording, on-device. A Rust library with an
iOS-first build (UniFFI to a Swift XCFramework). Audio is analysed once and can then be decoded
against many candidate readings, or turned into a tone lattice for other systems to rescore.

**Status:** P0 in progress. The design is in [`docs/superpowers/specs/`](docs/superpowers/specs/2026-09-28-tone-assessment-design.md)
and the plan is in [`docs/superpowers/plans/`](docs/superpowers/plans/2026-09-28-tonekit-p0.md).

## Scope

- Input is 16 kHz mono PCM. Everything runs locally: there is no network access. tonekit keeps no
  audio: it returns results and drops the samples; apps should discard recordings unless the user
  explicitly saves a clip (spec §11.3).
- The output is a distance and a likelihood, not a classification, plus advice such as "start
  higher".
- Languages, accents and speaker styles are data (packs), not code.
- The core crates are pure functions with no threads, filesystem, clock or randomness.

## Misuse boundary

Grading, decoding and accent fit are always relative to **caller-supplied targets and accents**.
tonekit ships no L1, dialect, origin or nativeness identification API or model, and won't accept
one. Accent fit over a learner-chosen short list, on the learner's own audio, on-device, is inside
that boundary.

Related limits (spec §11.3–11.4):

- No speaker embeddings, ever. A `Register` is four numbers and a `StyleProfile` is per-tone mean
  contours: pitch-shape statistics, not timbre.
- tonekit ships the mechanism for style profiles and no profiles of named people. It does no voice
  modelling.

## Data and licensing

- Code is `MIT OR Apache-2.0` ([`LICENSE-MIT`](LICENSE-MIT), [`LICENSE-APACHE`](LICENSE-APACHE)).
- [`deny.toml`](deny.toml) enforces the dependency policy: permissive licenses only (MPL-2.0 for
  the UniFFI crates), no GPL, LGPL, AGPL or SSPL, and no network or TLS crates.
- [`data-register.csv`](data-register.csv) lists every data source and its terms. Synthetic or TTS
  audio is never used to fit shipped calibration. Every data file of a shipped pack (the pack
  TOML and its calibration) is listed in that pack's `PROVENANCE.toml`, which `tkh provenance`
  checks against the register, and the gate verdict is only issued over real recordings the
  register allows.

## Layout

| Path | Contents |
|---|---|
| `crates/tonekit-core` | Plain data types shared by every crate |
| `crates/tonekit-f0` | f0 and energy tracks: the pYIN provider, octave repair, signal-quality checks |
| `crates/tonekit-segment` | Speech region, syllable nuclei and candidate syllable boundaries |
| `crates/tonekit-shape` | Speaker register, Chao-scale normalisation, tone-shape extraction, style fitting |
| `crates/tonekit-pack` | Language packs: TOML schema, loading, validation, context-dependent expected shapes |
| `crates/tonekit-decode` | Closed-set candidate decoding and the open per-syllable tone lattice |
| `crates/tonekit-fuse` | Evidence fusion into calibrated probabilities, and the utterance assessment |
| `crates/tonekit` | The facade: `analyze` once, then `decode`, `lattice` or `assess` |
| `crates/tonekit-cli` | The `tonekit` command line, for quick local checks on WAV files |
| `crates/tonekit-ffi` | UniFFI bindings: the Swift API, built for iOS |
| `crates/tonekit-py` | PyO3 bindings: the same library for Python, JSON in and JSON out |
| `crates/tonekit-testkit` | Dev-only deterministic synthetic voiced audio with exact f0 ground truth |
| `packs/` | Language packs as data: the pack TOML, its calibration JSON and a `PROVENANCE.toml` per pack |
| `harness/` | The Python evaluation harness (`tkh`): corpus manifest, gate metrics, synthetic tests, f0 bakeoff |
| `scripts/` | Build and check scripts for the iOS XCFramework and the generated Swift bindings |
| `swift/` | The SwiftPM package that wraps the XCFramework, with the Swift tests |
| `fixtures/` | A shared spoken example and the assessment every front end must reproduce |
| `docs/` | Design spec, plan, prior-art research, [decisions](docs/decisions.md) and iOS verification |

## Build and test

Rust 1.85 or newer (`rust-toolchain.toml` asks for stable):

```sh
cargo build --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo deny check        # the dependency policy in deny.toml
```

## Command line

```sh
cargo run --release -p tonekit-cli -- assess --pack packs/cmn/cmn.toml \
  --tones "4 1 3" fixtures/spoken-413.wav          # one row per syllable, then the utterance
cargo run --release -p tonekit-cli -- lattice --pack packs/cmn/cmn.toml fixtures/spoken-413.wav
```

Both commands take `--calib` (default: `<pack stem>.calib.json` beside the pack, if it exists),
`--accent` and `--json`; `assess` also takes `--labels`, `--distractor` and `--compare-accent`.
Input is a 16 kHz mono WAV, PCM16 or 32-bit float (`tkh ingest` converts recordings).

## Swift and iOS

`tonekit-ffi` exports the library to Swift through UniFFI. `scripts/build-xcframework.sh` (macOS
with Xcode) builds the static libraries for the device and the Apple-silicon Simulator, generates
the bindings and packages `build/Tonekit.xcframework` into the Swift package in
`swift/TonekitSmoke`. [`docs/ios-verification.md`](docs/ios-verification.md) is the checklist for
building it and running the Swift tests on the iOS Simulator. On Linux,
`scripts/check-swift-bindings.sh` checks the generated API.

## Python

`crates/tonekit-py` builds the `tonekit_py` module with maturin. Every function takes and returns
JSON text in the same serde format as the CLI and the Swift package, so the numbers are the same:

```python
import tonekit_py
analysis = tonekit_py.analyze(pcm, 16_000)                                    # 16 kHz mono floats
assessed = tonekit_py.assess(analysis, pack_toml, calib_json, request_json)   # "tonekit.assessment.v1"
```

`analyze`, `decode`, `lattice` and `assess` are documented in `crates/tonekit-py/tonekit_py.pyi`.
The harness depends on the module, so `uv sync` in `harness/` builds it (it needs a Rust
toolchain).

## Evaluation harness

From `harness/` (`uv sync --locked`, then `uv run tkh <command>`):

| Command | What it does |
|---|---|
| `tkh ingest DIR` | Convert recordings to 16 kHz mono float32 WAV |
| `tkh eval` | Grade a corpus manifest and write the gate report (S1, leave-one-pair-out). Only real recordings allowed by `data-register.csv` earn a PASS or FAIL: anything else is reported as `NOT A GATE`, or `SMOKE (synthetic)` with `--allow-synthetic` |
| `tkh synth`, `tkh adversary` | Synthetic perturbations of correct clips (WORLD resynthesis), and a random search for false accepts and rejects. Tests and diagnostics only; never used to fit calibration |
| `tkh bakeoff` | pYIN against SwiftF0 as the runtime f0: accuracy under noise, and the gate |
| `tkh provenance` | Check every pack's `PROVENANCE.toml` against `data-register.csv`: each data file in a pack must be listed and each source cleared |

The recording protocol and the manifest format are in `harness/corpus/PROTOCOL.md`. Run the
harness tests with `uv run pytest`.

## Decisions

The design choices that shaped behaviour and data, with their reasons and what each costs if it
turns out wrong, are in [`docs/decisions.md`](docs/decisions.md). Code comments cite them as `R<n>`.
