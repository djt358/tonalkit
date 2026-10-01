# S0.5 contracts

*These are the formats the S0.5 lanes build against. Each format has one owner module, and
everything else imports it. If a lane needs a change here, it says so in its report; nobody
forks a format locally.*

| Format | Lives in | Python model (owner) |
|---|---|---|
| Prompt deck | `kit/deck/*.toml` (repo) | `tonekit_harness.contracts.deck` |
| Session bundle (what the kit exports) | a zip the speaker sends DJ | `tonekit_harness.contracts.bundle` |
| Data root, corpus registry, speakers | `$TONEKIT_DATA` (never the repo) | `tonekit_harness.contracts.registry` |
| Manifest additions | `manifest.jsonl` in a corpus dir | `tonekit_harness.manifest` (extended) |
| Gate file | `gates/*.toml` (repo) | `tonekit_harness.contracts.gate` |
| Purge log | `$TONEKIT_DATA/purge-log.jsonl` | `tonekit_harness.contracts.registry` |

All models are pydantic v2 with `extra="forbid"`, like `manifest.Clip`. `tkh schema` writes their
JSON Schemas to `kit/schema/`, and the kit's JavaScript tests validate against those.

## 1. Prompt deck (`kit/deck/<id>.toml`)

A deck is the single source of truth for what each card shows and what a correct or deliberately
wrong reading of it is. The kit only records card ids; intake joins them back to the deck.

```toml
[deck]
id = "s05-v1"
lect = "cmn"
version = 1
title = "Mandarin tones: phrases and words"

[[card]]
id = "g01-c"                     # unique in the deck; [a-z0-9-]+
set = "gate"                     # gate | diag_t23 | diag_count | diag_minimal | register | quiet
pair = "g01"                     # required for gate/diag pairs, else omitted
label = "correct"                # correct | tone_error | n/a
text = "一杯水"                   # what the card shows
pinyin = "yì bēi shuǐ"           # surface (spoken) form, sandhi applied; shown in hanzi+pinyin mode
citation_pinyin = "yī bēi shuǐ"  # dictionary form, for the sandhi check
context = "phrase"               # phrase (sandhi applies) | isolated (citation, "solitaire")
intended = { id = "g01", tones = ["4", "1", "3"], labels = ["yi", "bei", "shui"] }
produced_tones = ["4", "1", "3"] # what the card asks to be said
distractors = []                 # candidates, same shape as `intended`
prompt_note = ""                 # optional, shown under the card (see the error-card example)
status = "unverified"            # unverified | approved (DJ audit); the kit ships approved cards only

[[card]]
id = "g01-e"
set = "gate"
pair = "g01"
label = "tone_error"
text = "一杯睡"
pinyin = "yì bēi shuì"
citation_pinyin = "yī bēi shuì"
context = "phrase"
intended = { id = "g01", tones = ["4", "1", "3"], labels = ["yi", "bei", "shui"] }
produced_tones = ["4", "1", "4"]
prompt_note = "Read it as written: 睡 as in 睡觉."
status = "unverified"
```

Rules the model enforces:
- tones are pack tone ids;
- `len(tones) == len(labels)`;
- `produced_tones` has the intended length;
- `correct` ⇒ `produced_tones == intended.tones`;
- `tone_error` ⇒ they differ in exactly one position;
- each gate pair has one `correct` and one `tone_error` card;
- `context = "phrase"` ⇒ `intended.tones` equals the sandhi of `citation_pinyin`'s tones (一, 不,
  T3+T3; the deck builder's checker);
- `context = "isolated"` ⇒ they're equal with no sandhi.

`status = "approved"` is set by DJ's audit only.

## 2. Session bundle (the zip the kit exports)

```
tonekit-<deck id>-<session code>.zip
  session.json
  clips/<card id>.wav        # 16 kHz, mono, 16-bit PCM; the last kept take only
```

`session.json`:

```json
{
  "schema": "tonekit.session.v1",
  "deck": {"id": "s05-v1", "sha256": "<hex of the deck file the kit loaded>"},
  "session": "K7Q2MD",
  "started_at": "2026-10-03T18:02:11Z",
  "finished_at": "2026-10-03T18:24:40Z",
  "consent": {"version": "v1", "agreed_at": "2026-10-03T18:02:30Z"},
  "speaker": {
    "background": "native",
    "grew_up_hearing": "taiwan",
    "reading": "hanzi+pinyin"
  },
  "device": {
    "user_agent": "...",
    "input_sample_rate": 48000,
    "constraints": {"echoCancellation": false, "noiseSuppression": false, "autoGainControl": false}
  },
  "clips": [
    {"card": "g01-c", "file": "clips/g01-c.wav", "takes": 2, "duration_s": 1.42, "peak": 0.51}
  ],
  "skipped": ["d05-a"]
}
```

- **`session`** is six characters from an unambiguous alphabet (no 0/O/1/I), random, made by the
  kit. The kit shows it at the end: "Keep this code if you ever want your recordings deleted." It
  is the only key for a deletion request. No names, emails or contact details appear anywhere.
- **`speaker`** fields are enums.
  - `background`: `native`, `heritage`, `learner` or `prefer_not`.
  - `grew_up_hearing`: `mainland`, `taiwan`, `singapore_malaysia`, `hong_kong_macau`, `other`
    or `prefer_not`.
  - `reading`: `hanzi` or `hanzi+pinyin`.
- **`device`** records the actual input rate and the constraints the browser reported, not the
  ones requested.

## 3. Data root and corpus registry (`$TONEKIT_DATA`)

Volunteer audio and speaker metadata **never** enter the repository. They live under a data root:
`$TONEKIT_DATA`, default `~/tonekit-data`, with `tkh --data PATH` overriding it.

```
$TONEKIT_DATA/
  corpora/<corpus id>/corpus.toml
  corpora/<corpus id>/manifest.jsonl
  corpora/<corpus id>/audio/...
  inbox/                      # bundles waiting for intake
  purge-log.jsonl
```

`corpus.toml`:

```toml
[corpus]
id = "volunteers-2026-10"
source = "volunteer-corpus"    # a data-register.csv id
kind = "recorded"              # recorded | public | synthetic
lect = "cmn"
manifest = "manifest.jsonl"

[[speaker]]
id = "v-k7q2md"                # v-<session code> for volunteers; corpus-native ids for public sets
background = "native"
grew_up_hearing = "taiwan"
accent = "cmn-TW"              # the accent this speaker is graded against (pack accent id)
split = "gate"                 # gate | dev | calib | heldout
sessions = ["K7Q2MD"]
```

- **Splits.**
  - Volunteer and DJ speakers default to `gate`.
  - Public corpora are split by speaker, deterministically by hash: calib 60%, dev 20%,
    heldout 20%.
- **Default `accent`.** `taiwan` maps to `cmn-TW` and everything else to `cmn-standard`.
- **Refusals.**
  - Anything that fits parameters refuses `gate` and `heldout` speakers.
  - Gates refuse `synthetic` corpora, plus any source not cleared in the register for the use.
- **Composition.** A selection is a union across corpora, e.g. the volunteers' and DJ's gate
  speakers together, or public `calib` with volunteer `gate`. Selection is always by corpus id or
  glob plus split plus set. Nothing is hard-wired to one corpus.

## 4. Manifest additions (`manifest.Clip`)

New optional fields, which existing manifests keep validating without:

```
card: str | None       # deck card id
deck: str | None       # deck id
take: int | None       # takes recorded for the kept clip
context: "phrase" | "isolated" | None
```

`speaker` refers to a `[[speaker]]` id in the clip's corpus, and graders read the accent from
there. The CLI's `--accent` stays as an override.

## 5. Gate file (`gates/<id>.toml`)

```toml
[gate]
id = "s1"
phase = "p0"
summary = "Tone errors are told apart from correct readings on real speech"

[select]
corpora = ["*"]
kinds = ["recorded"]
splits = ["gate"]
sets = ["gate"]

[thresholds]
method = "loso"                  # leave-one-speaker-out; "lopo" (leave-one-pair-out) for one speaker

[[criterion]]
metric = "correct_accept"
min = 0.90

[[criterion]]
metric = "wrong_accept"
max = 0.10

[requires]
speakers_min = 1
l1_min = 1                       # P1's gate sets 3, and needs English among them

[report]
by = ["speaker", "background", "grew_up_hearing", "context"]
diagnostics = ["candidate_id_accuracy", "count_robustness", "t23_confusion"]
```

- **Metrics** are named entries in one registry in `metrics.py`, and unknown names are errors.
- **Measured elsewhere.** A metric that can't be computed here (P1's iPhone 12 latency) names an
  `[[input]]` file with its value and provenance. A missing input makes the verdict
  `INCOMPLETE`, listing what's missing.
- **P2's code check.** P2's "no diff outside `packs/` and the harness loaders" is a
  `[[check]] kind = "paths_unchanged"` entry against a base ref.

## 6. Purge (`tkh purge --session CODE`)

Removes, for that session:
- the audio;
- the manifest rows;
- the speaker entry;
- analysis-cache entries (keyed by WAV hash);
- review pages that embed the audio;
- any bundle left in `inbox/`.

Then:
- **Stale outputs:** it marks the scoreboard and any calibration fitted on that corpus as stale.
  The next `tkh score` re-runs, and a stale calibration can't ship.
- **Log:** it appends `{"session", "purged_at", "files_removed", "corpora"}` to `purge-log.jsonl`.
- **Repeat runs:** it is idempotent, and it reports "nothing found" for an unknown code.
