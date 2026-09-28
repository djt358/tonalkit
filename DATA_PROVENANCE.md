# Data provenance

Every dataset, model and service that touches tonekit is listed in
[`data-register.csv`](data-register.csv). Every shipped calibration file carries a
`PROVENANCE.toml` next to it, and CI checks that file against the register.

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

Each shipped calibration (for example `packs/cmn/PROVENANCE.toml`) lists what it was fitted on:

```toml
artifact = "cmn.calib.json"
note = "what this calibration is and where the numbers came from"

[[source]]
id = "aishell-3"            # a data-register.csv id
use = "native calibration"  # what the source was used for

[[signoff]]
id = "ompal"                # the verify source this signs off
by = "DJ"
date = "2026-09-28"
note = "why the terms are acceptable"
```

- `artifact` and `note` are free text.
- `[[source]]` tables are optional. A file with no `[[source]]` has zero sources, which is what
  seed values that were not fitted on data look like.
- `[[signoff]]` tables are optional. A sign-off matches a source by `id`.

## The check

```
cd harness
uv run tkh provenance --register ../data-register.csv ../packs/*/PROVENANCE.toml
```

It prints one line per violation and exits 1 if there are any; otherwise it prints
`provenance ok` and exits 0. A source is a violation when:

- its `id` is not in the register,
- its `shipped_weights_training` is `deny`, even with a sign-off,
- its `shipped_weights_training` is `verify` and the file has no `[[signoff]]` with the same `id`,
- its `shipped_weights_training` is `n/a`, or is any value other than the four above.

A manifest that can't be read or isn't valid TOML, or a `[[source]]` or `[[signoff]]` without a
string `id`, is also a violation. The `harness` job in `.github/workflows/ci.yml` runs the check on
every push and pull request.

To clear a `verify` source properly, confirm its terms and update its row in the register. A
`[[signoff]]` records a person's decision to use it while the terms are still unconfirmed.

## Synthetic audio never fits shipped calibration

Synthetic and TTS audio (`synthetic-world`, `apple-system-tts`) are for tests and diagnostics. They
never fit shipped calibration, and gates are always measured on real recordings. Both are `deny` in
the register, so listing either as a `[[source]]` fails the check.
