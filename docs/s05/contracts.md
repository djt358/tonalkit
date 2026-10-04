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
set = "gate"                     # gate | diag_t23 | diag_count | diag_minimal | diag_context | register | quiet
pair = "g01"                     # required for gate/diag pairs, else omitted
label = "correct"                # correct | tone_error | n/a
text = "一杯水"                   # what the card shows (simplified)
text_traditional = "一杯水"       # optional; shown when the speaker reads traditional (R74); default `text`
pinyin = "yì bēi shuǐ"           # surface (spoken) form, sandhi applied; shown in hanzi+pinyin mode
citation_pinyin = "yī bēi shuǐ"  # dictionary form, for the sandhi check
context = "phrase"               # phrase (sandhi applies) | isolated (citation, "solitaire")
intended = { id = "g01", tones = ["4", "1", "3"], labels = ["yi", "bei", "shui"] }
produced_tones = ["4", "1", "3"] # what the card asks to be said
distractors = []                 # candidates, same shape as `intended`
prompt_note = ""                 # optional, shown under the card (see the error-card example)
prompt_note_traditional = ""     # optional, needs prompt_note; shown instead when the speaker reads traditional (R88)
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
prompt_note_traditional = "Read it as written: 睡 as in 睡覺."
status = "unverified"
```

Rules the model enforces:
- tones are pack tone ids;
- `len(tones) == len(labels)`;
- `produced_tones` has the intended length;
- `correct` ⇒ `produced_tones == intended.tones`;
- `tone_error` ⇒ they differ in exactly one position;
- pairs are scoped to `(set, pair)`; `pair` is required in `gate` and `diag_t23` and optional
  elsewhere; a pair in those two sets is exactly one `correct` and one `tone_error` card with equal
  `intended.tones` (R66, R81). In other sets `pair` only groups cards. `diag_minimal` cards are all `correct` readings of different words; a
  card lists at least one other member's intended reading as a `distractor` (R76, R81);
- `diag_context` cards contrast the citation ("solitaire", `isolated`) and sandhi (`phrase`)
  readings of the same syllables: 一 / 一杯 / 一块, 不 / 不对, 水 / 水果; they are `correct`
  readings (R76, R81);
- `context = "phrase"` ⇒ each card's own `produced_tones` equal the sandhi of its own
  `citation_pinyin` (一, 不, T3 runs with every binary bracketing; R63–R65; a neutral syllable
  written as neutral keeps the T3 before it, R89), and `pinyin` shows
  `produced_tones`. On a correct card that is also `intended.tones`; on an error card it is the
  erroneous surface form. An error whose changed syllable alters a neighbour's sandhi changes two
  surface tones and is refused: pick error words that change one surface tone only;
- `context = "isolated"` ⇒ `produced_tones` equal the citation tones, no sandhi;
- a `correct` card has exactly one native reading: a phrase whose citation allows more than one
  surface (a T3 run of three or more with two groupings, e.g. 一把雨伞) is refused, because one
  `produced_tones` list would grade the other native reading wrong (R89);
- `text_traditional`, when present, has the same length as `text`; `prompt_note_traditional`
  only appears with `prompt_note`.

`status = "approved"` is set by DJ's audit only: the deck builder reads
`kit/deck/sources/approvals.csv` (`card_id, fingerprint, decision, note`, written by `tkh deck
approve`) and approves a card only while its fingerprint still matches; `tkh deck check --ship`
fails unless every card is approved and every pair and minimal set is whole (R91).

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
    "reading": "hanzi+pinyin",
    "script": "traditional"
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
  - `script`: `simplified` or `traditional` (R74), asked with the reading question; the kit shows
    `text_traditional` where a card has one.
- **`device`** records the actual input rate and the constraints the browser reported, not the
  ones requested. `constraints` always has all three keys, each `true`, `false` or `null`; `null`
  means the browser didn't report it (iOS Safari omits `noiseSuppression` and `autoGainControl`;
  R83).

## 3. Data root and corpus registry (`$TONEKIT_DATA`)

Volunteer audio and speaker metadata **never** enter the repository. They live under a data root:
`$TONEKIT_DATA`, default `~/tonekit-data`, with `tkh --data PATH` overriding it.

```
$TONEKIT_DATA/
  corpora/<corpus id>/corpus.toml
  corpora/<corpus id>/manifest.jsonl
  corpora/<corpus id>/audio/...
  corpora/<corpus id>/audio/<CODE>/<card id>.wav  # intake: a session's clips, byte for byte
  corpora/<corpus id>/sessions/<CODE>.json        # intake: the session's session.json, byte for byte
  inbox/                      # bundles waiting for intake
  stale/<corpus id>.json      # outputs made from this corpus are stale (purge, relabel); cleared by the next run
  reports/<corpus id>.md      # where intake tells `tkh eval` to write (reports list clips by session code)
  purge-log.jsonl
```

A stale marker (`contracts.registry.StaleMarker`) is `{"corpus": "<id>", "reasons": [{"reason":
"purged session K7Q2MD", "marked_at": "<UTC time>"}]}`; marking again appends a reason, and a
marker that can't be read is replaced by one that says so.

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
accent = "cmn-TW"              # optional: the pack accent id this speaker is graded against (R82)
split = "gate"                 # gate | dev | calib | heldout
sessions = ["K7Q2MD"]
```

- **Splits.**
  - Volunteer and DJ speakers default to `gate`.
  - Public corpora are split by speaker, deterministically by hash: calib 60%, dev 20%,
    heldout 20% (R69). For `public` and `synthetic` corpora the model refuses a stored split that
    differs from the hash; `recorded` corpora can move speakers between splits (R72, R82).
- **Default `accent`.** When a speaker has none: `taiwan` maps to `cmn-TW` and everything else to
  `cmn-standard`. Accents are checked against the pack's accent ids at load (R82).
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
there. Intake writes each clip's `source` as its corpus's `source`: WORLD resynthesis refuses
`volunteer-corpus` clips by that field (R80). The CLI's `--accent` stays as an override.

Rows intake writes: `id` is `<CODE>-<card id>`, and `pair` is `<CODE>-<deck pair>`, since a
manifest holds many speakers and a gate pair is one speaker's two readings (the deck's pair is
`card`'s). `condition` is `{"noise": "uncontrolled", "distance": "handheld"}`; `needs_listen` is
false. A recorded `gate` or `diag_t23` card whose twin was skipped gets no row (pairs are graded
whole).

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
# P1 adds l1 requirements (speakers_l1_min, l1_include) with a Speaker.l1 field (R73); until then
# p1.toml reports them as missing inputs.

[report]
by = ["speaker", "background", "grew_up_hearing", "context"]
diagnostics = ["candidate_id_accuracy", "count_robustness", "t23_confusion"]
```

- **Metrics** are named entries in one registry in `metrics.py`, and unknown names are errors.
- **Measured elsewhere.** A metric that can't be computed here (P1's iPhone 12 latency) names an
  `[[input]]` (`metric`, `file` relative to the gate file with no `..`, `summary`) holding its
  value and provenance. A missing input makes the verdict `INCOMPLETE`, listing what's missing
  (R67).
- **P2's code check.** P2's "no diff outside `packs/` and the harness loaders" is a
  `[[check]]` entry (`id`, `kind = "paths_unchanged"`, `base`, `paths` as git pathspecs for
  `git diff <base> -- <paths>`, `summary`; R67).

## 6. Purge (`tkh purge --session CODE`)

Removes, for that session:
- the audio;
- the manifest rows;
- the speaker entry;
- analysis-cache entries: the cache keys an entry by a hash over the WAV, the register and the
  tonekit build, so one session's entries can't be picked out and purge clears the whole cache;
- review pages that embed the audio (none yet: `tkh review` must write them where purge looks);
- reports under `$TONEKIT_DATA/reports/` that mention the session (they list clips by id;
  the next `tkh eval` makes new ones);
- everything intake wrote for it: the copy of `session.json` (intake keeps no QC rows yet), and
  any staging area an interrupted intake left;
- any bundle left in `inbox/` (by name, or by the code in its `session.json`).

What the engine can't reach is DJ's: the original zip in Messages, Mail, Downloads or Files. The
purge output ends with that reminder.

Then:
- **Stale outputs:** it marks the scoreboard and any calibration fitted on that corpus as stale.
  The next `tkh score` re-runs, and a stale calibration can't ship.
- **Log:** it appends `{"session", "purged_at", "files_removed", "corpora"}` to `purge-log.jsonl`;
  `files_removed` is a count, never names (R68).
- **Repeat runs:** it is idempotent, and it reports "nothing found" for an unknown code.
