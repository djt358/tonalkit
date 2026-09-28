# tonekit

Grades lexical tone (Mandarin first) from a short recording, on-device. A Rust library with an
iOS-first build (UniFFI to a Swift XCFramework). Audio is analysed once and can then be decoded
against many candidate readings, or turned into a tone lattice for other systems to rescore.

**Status:** P0 in progress. The design is in [`docs/superpowers/specs/`](docs/superpowers/specs/2026-09-28-tone-assessment-design.md)
and the plan is in [`docs/superpowers/plans/`](docs/superpowers/plans/2026-09-28-tonekit-p0.md).

## Scope

- Input is 16 kHz mono PCM. Everything runs locally: there is no network access, and PCM is
  discarded after analysis.
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
  audio is never used to fit shipped calibration, and every shipped calibration file carries a
  `PROVENANCE.toml` checked against the register.

## Layout

| Path | Contents |
|---|---|
| `crates/tonekit-core` | Plain data types shared by every crate |
| `docs/` | Design spec, plan and prior-art research |

More crates arrive as the plan progresses.
