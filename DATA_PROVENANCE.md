# Data provenance

Every dataset, model and service that touches tonekit is listed in
[`data-register.csv`](data-register.csv). Every shipped pack directory carries a `PROVENANCE.toml`
that lists each of the pack's data files (the pack TOML and its calibration), and CI checks that
file against the register.

## `data-register.csv`

One row per source. The columns are:

| Column | Meaning |
|---|---|
| `id` | Short stable id. `PROVENANCE.toml` refers to sources by this id. |
| `kind` | `code`, `model`, `dataset` or `service`. |
| `name`, `license`, `commercial_ok` | What it is and the terms as we understand them. |
| `shipped_code` | Verdict for shipping it as code or a model file in the library. `tkh provenance` doesn't read this column; Rust dependency licences are enforced by `deny.toml`. |
| `shipped_weights_training` | Verdict for fitting shipped weights or calibration on it: `allow`, `verify`, `deny` or `n/a`. This is the column `tkh provenance` enforces. |
| `role`, `verified_via`, `source_url`, `notes` | How we use it, how the terms were checked, and anything a reader needs to know. |

`shipped_weights_training` values:

- `allow`: may be used to fit shipped calibration.
- `verify`: the terms are unconfirmed. It may be used only with a recorded sign-off.
- `deny`: must never be used to fit shipped calibration.
- `n/a`: not a dataset or weights source (a code dependency or a tool), so it can't appear as a
  source of calibration.

## `PROVENANCE.toml`

Every pack directory (for example `packs/cmn/`) holds a `PROVENANCE.toml` that describes its
data files (the pack TOML and its calibration) and lists what they were fitted on:

```toml
artifacts = ["packs/cmn/cmn.toml", "packs/cmn/cmn.calib.json"]
note = "what these files are and where the numbers came from"

[[source]]
id = "aishell-3"            # a data-register.csv id
use = "native calibration"  # what the source was used for

[[signoff]]
id = "ompal"                # the verify source this signs off
by = "DJ"
date = "2026-09-28"
note = "why the terms are acceptable"
```

The format is strict, so that a typo can't look like a clean file:

- The only top-level keys are `artifact`, `artifacts`, `note`, `source` and `signoff`. Anything
  else, such as `[[sources]]` or `[[Source]]`, is a violation, and the message suggests the
  closest valid name.
- `note` is a required non-empty string. Exactly one of `artifact` (a path) and `artifacts` (a
  non-empty list of paths) is required. The paths name the data files this record describes,
  relative to the repo root (here `packs/cmn/cmn.toml` and `packs/cmn/cmn.calib.json`).
- Every `*.toml` and `*.json` file in the pack directory, at any depth, other than
  `PROVENANCE.toml` itself, must be one of those paths. A data file nobody attested (the pack TOML
  that P1 will fit, a second calibration) fails the check.
- `[[source]]` tables are optional, each with a string `id` (and a free-text `use`). A file with
  no `[[source]]` has zero sources, which is what seed values that were not fitted on data look
  like.
- `[[signoff]]` tables are optional, each with a string `id` that matches a source and a non-empty
  string `by`. `date` and `note` are recorded by convention and not checked.

## The check

```
cd harness
uv run tkh provenance --register ../data-register.csv --packs-root ../packs
```

`--packs-root DIR` covers every pack. Each immediate subdirectory of `DIR` must contain a
`PROVENANCE.toml` whose artifacts exist inside that directory (paths are resolved against the
parent of `DIR`, the repo root) and cover every data file in it. A pack without one fails the
check, so a new pack can't ship a calibration without provenance. Every `PROVENANCE.toml` found is then checked as described below. You can
also pass `PROVENANCE.toml` files explicitly, alone or in addition to `--packs-root`.

It prints one line per violation and exits 1 if there are any; otherwise it prints
`provenance ok` and exits 0 (a missing register file exits 2). A source is a violation when:

- its `id` is not in the register,
- its `shipped_weights_training` is `deny`, even with a sign-off,
- its `shipped_weights_training` is `verify` and the file has no `[[signoff]]` with the same `id`
  (and a non-empty `by`),
- its `shipped_weights_training` is `n/a`, or is any value other than the four above.

Anything that breaks the format above is also a violation: an unknown top-level key, a missing or
empty `artifact`, `artifacts` or `note`, both `artifact` and `artifacts`, a `[[source]]` or
`[[signoff]]` without a string `id`, a `[[signoff]]` without a non-empty `by`, a manifest that
can't be read or isn't valid TOML, an artifact that doesn't exist or lies outside the pack
directory, a data file in the pack that no artifact names, a pack directory with no
`PROVENANCE.toml`, and a `--packs-root` that is missing or holds no packs. The `harness` job in `.github/workflows/ci.yml` runs the check
on every push and pull request.

To clear a `verify` source properly, confirm its terms and update its row in the register. A
`[[signoff]]` records a person's decision to use it while the terms are still unconfirmed.

## Volunteer recordings

Recordings from the S0.5 volunteer kit are the `volunteer-corpus` row in the register. They are
made on the volunteers' own phones, with the consent text in [`kit/CONSENT.md`](kit/CONSENT.md)
(version `v1`; every session records the version its speaker agreed to).

- **What each promise rests on.** [`kit/PROMISES.md`](kit/PROMISES.md) maps every promise in the
  consent and the guide to the mechanism that keeps it and the test that would fail if it broke.
- **Where the data lives.** Under `$TONEKIT_DATA`, never in the repository: audio is blocked from
  git (`scripts/check-no-audio.sh`), and speakers are known only by pseudonymous session codes and
  enum-only background answers.
- **What it may be used for.** The row's `shipped_weights_training` is `verify`: S1 gate and
  evaluation only. Moving volunteer speakers into calibration waits for DJ to confirm the consent
  wording, and a `PROVENANCE.toml` listing `volunteer-corpus` as a source then needs a
  `[[signoff]]` like any other `verify` source.
- **Deletion.** A volunteer's session code is the only key. `tkh purge --session CODE` removes
  that session and logs it (`docs/s05/contracts.md` §6).

## Synthetic audio never fits shipped calibration

Synthetic and TTS audio (`synthetic-world`, `apple-system-tts`) are for tests and diagnostics. They
never fit shipped calibration, and gates are always measured on real recordings. Both are `deny` in
the register, so listing either as a `[[source]]` fails the check.

The gate verdict follows the same rule. `tkh eval` and `tkh bakeoff --gate` read each clip's
`source` (which must be a register id) and issue PASS or FAIL only when no clip is synthetic (the
`synthetic-world` source, a `synthetic` field or the `synthetic` set) and every clip's source is
`allow` in `shipped_weights_training`. Otherwise the report says `NOT A GATE (n synthetic /
non-allowed clips)`, or `SMOKE (synthetic)` when `--allow-synthetic` marks a smoke run, and the
command still exits 0. A manifest that mixes synthetic clips into a gate set is an error.

A source whose weights or training data are unchecked is `verify` until someone clears it: SwiftF0
is `verify` until the licences of the data it was trained on (the `swift-f0-training` repository)
are checked, and its weights must not ship before then (spec §11.2).
