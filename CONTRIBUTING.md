# Contributing

tonekit is early (P0), so expect the design to move. For anything larger than a small fix, open an
issue first and say what you want to change and why.

## Setup

- Rust 1.85 or newer. `rust-toolchain.toml` pins stable with rustfmt and clippy.
- For the harness and the Python bindings: Python 3.11+ and [uv](https://docs.astral.sh/uv/).
  `uv sync` in `harness/` builds the Rust extension, so it needs the Rust toolchain. pyworld builds
  from source on Linux and macOS, which needs a C++ compiler.
- For iOS: a Mac with Xcode 15+ and an iOS 17+ Simulator. The steps are in
  [`docs/ios-verification.md`](docs/ios-verification.md).

## Before you open a pull request

CI runs these checks, and a pull request should pass them locally first:

```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cargo deny check

cd harness
uv sync --locked
uv run pytest
uv run pytest ../crates/tonekit-py/tests
uv run tkh provenance --register ../data-register.csv --packs-root ../packs
```

If you change the Swift bindings or the FFI surface, also run `scripts/check-swift-bindings.sh` on
Linux, or follow the Mac checklist.

## How the code is organised

- **Files.** Small files with one responsibility each. A crate or module that grows two concerns
  gets split along the seam.
- **Tests first.** Add a failing test, then the fix. A behaviour worth changing is worth pinning.
- **Core crates stay pure.** `tonekit-core`, `-f0`, `-segment`, `-shape`, `-pack`, `-decode`,
  `-fuse` and `tonekit` use no threads, filesystem, clock or randomness. I/O belongs in the CLI,
  the bindings and the harness.
- **Numbers crossing a boundary are finite.** JSON, Swift and Python never see NaN or infinity
  (R12).
- **One set of numbers.** The CLI, Swift and Python must reproduce
  `fixtures/spoken-413.assessment.json` within 1e-4. If a change moves it, regenerate it with
  `UPDATE_FIXTURES=1 cargo test -p tonekit-cli` and say why in the pull request.

## Design decisions

When a change settles something the spec leaves open, contradicts, or can't be built as written,
add an entry to [`docs/decisions.md`](docs/decisions.md) with the next `R<n>`. Say what was
decided, why, and what it costs if wrong. Cite the id in the code comment. A test checks that every
cited id has an entry.

## Data, packs and provenance

- Languages and accents are data in `packs/`, not code. A pack's data files must all be listed in
  its `PROVENANCE.toml`, and every source must be a row in `data-register.csv`. `tkh provenance`
  checks both. See [`DATA_PROVENANCE.md`](DATA_PROVENANCE.md).
- Don't commit recordings of anyone without a register row and their release.
- Synthetic or TTS audio is for tests and diagnostics only. It never fits shipped calibration, and
  it never counts toward the gate.

## Scope limits

Some contributions won't be accepted, however they're framed ([README](README.md#misuse-boundary),
spec §11):

- identifying a speaker's first language, dialect, origin or nativeness;
- speaker embeddings or voice modelling;
- style profiles of named people.

Grading is always relative to targets and accents the caller supplies.

## Licence

tonekit is dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.
Unless you explicitly state otherwise, any contribution you intentionally submit for inclusion is
dual-licensed the same way, without any additional terms or conditions.
