# DJ P0 corpus: recording protocol

This is the recording protocol for the owned P0 gate corpus (plan Task 18) and the manifest
format the harness reads. Everything recorded here is `dj-corpus` in `data-register.csv`, released
under the self-release in `RELEASE-dj.md` so that derived calibration can ship.

## Setup

- iPhone held at arm's length unless a set says otherwise.
- Café noise for `gate` and every `diag_*` set. `quiet` is recorded in a quiet room.
- Recordings go in `corpus/raw/`. `tkh ingest` converts them to 16 kHz mono float32 WAV in
  `corpus/dj/`.

## Sets

| `set` | What to record | Clips |
|---|---|---|
| `gate` | 20 pairs from `g_measure` spells (three syllables, e.g. 一杯水). Each pair is the correct spoken form plus one deliberate single-tone error. Label `produced_tones` exactly. | 40 |
| `diag_t23` | 10 pairs focused on T2/T3 confusion, plus 10 pairs with neutral-tone and half-third contexts. | 40 |
| `diag_count` | Hesitation before the spell (嗯…), restart, extra word, dropped syllable. | 10 |
| `diag_minimal` | 10 tone-minimal spell sets of 2 members each (买/卖, 水/睡 patterns). Record each member once; list the other member as a `distractor`. | 20 |
| `quiet` | 5 gate pairs re-recorded in a quiet room. | 10 |
| `register` | 妈麻马骂 ×8 (eight clips). Eight clips make 32 syllables, above tonekit's 30-syllable cold-start threshold, so gate clips are graded with a warm register and no ×1.5 tolerance widening. | 8 |
| `synthetic` | Not recorded. Derived clips (WORLD resynthesis) for tests and diagnostics only. | n/a |

The recorded sets total 128 clips (40 + 40 + 10 + 20 + 10 + 8). After writing the manifest, check
the count from `harness/`:

    uv run python -c "from tonekit_harness.manifest import load; print(len(load('corpus/manifest.jsonl')))"

It should print 128.

## Workflow

From `harness/`:

1. Record into `corpus/raw/`.
2. `uv run tkh ingest corpus/raw --out corpus/dj` converts every `.wav` there (stereo is averaged
   to mono, then resampled to 16 kHz). Without `--out`, the output goes to `corpus/ingested/`.
3. Add one row per clip to `corpus/manifest.jsonl`, then run the count check above. It fails with
   the file and line number of the first invalid row.
4. `uv run tkh eval --manifest corpus/manifest.jsonl --pack ../packs/cmn/cmn.toml --calib
   ../packs/cmn/cmn.calib.json --report reports/p0-gate.md` grades every clip, computes the
   leave-one-pair-out gate S1 (correct-accept at least 0.90, wrong-accept at most 0.10 over the 20
   gate pairs) and writes the report. It exits 0 whether or not the gate passes; the report's
   headline says which. A speaker's `register` clips are graded first and their register is
   used for that speaker's other clips. Analyses are cached in `.cache/analysis/` (keyed by the
   WAV bytes, the register and the installed `tonekit_py`); `--no-cache` bypasses the cache.

## Manifest: `corpus/manifest.jsonl`

One JSON object per line. Blank lines are skipped. Unknown keys are rejected, so a misspelt field
is an error instead of silently dropped data. The schema is `manifest.Clip`.

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Unique clip id, e.g. `gate-01-correct`. |
| `path` | string | The ingested WAV, relative to `corpus/` (e.g. `dj/gate-01-correct.wav`). |
| `speaker` | string | Speaker id, e.g. `dj`. |
| `set` | one of `gate`, `diag_t23`, `diag_count`, `diag_minimal`, `quiet`, `register`, `synthetic` | Which recording set the clip belongs to. |
| `pair` | string or null | Ties the correct and error clips of a pair together, e.g. `gate-01`. Null when the clip has no partner. |
| `label` | one of `correct`, `tone_error`, `graded`, `n/a` | What was recorded relative to `intended`. `n/a` when no correct/error judgement applies. |
| `intended` | candidate (required) | The reading the speaker was aiming for. |
| `distractors` | list of candidates (default empty) | Other readings to decode against, e.g. the other member of a minimal set. |
| `produced_tones` | list of strings or null | The tones actually produced, per syllable, labelled exactly. Null when not applicable. |
| `condition` | `{noise, distance}`, both strings | Recording conditions, e.g. `{"noise": "cafe", "distance": "arm"}`. |
| `source` | string | A `data-register.csv` id: `dj-corpus` for these recordings, `synthetic-world` for synthetic clips. |
| `synthetic` | object or null | For synthetic clips, how they were derived (source clip, perturbation). Null for real recordings. |
| `needs_listen` | bool (default false) | Set when a person must listen to the clip before its label is trusted (gate failures and adversarial finds). |

A candidate is `{"id": string, "tones": [string], "labels": [string]}`. `tones` has one entry per
syllable (cmn tone ids are `"1"` to `"5"`). `labels` may be shorter than `tones`, in which case the
missing labels are null, but never longer.

Example row:

    {"id": "gate-01-error", "path": "dj/gate-01-error.wav", "speaker": "dj", "set": "gate",
     "pair": "gate-01", "label": "tone_error",
     "intended": {"id": "yi4bei1shui3", "tones": ["4", "1", "3"], "labels": ["4", "1", "3"]},
     "distractors": [], "produced_tones": ["4", "2", "3"],
     "condition": {"noise": "cafe", "distance": "arm"}, "source": "dj-corpus",
     "synthetic": null, "needs_listen": false}
