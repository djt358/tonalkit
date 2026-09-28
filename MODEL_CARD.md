# Model card: `cmn` language pack

| | |
|---|---|
| Pack | `packs/cmn/cmn.toml`, lect `cmn`, **v0.2.0** |
| Calibration | `packs/cmn/cmn.calib.json` (seed values) |
| Provenance | `packs/cmn/PROVENANCE.toml`: zero data sources |
| Loaded by | `tonekit-pack` (`LanguagePack::from_toml`) |

## What it is

A data pack for Mandarin lexical tone: five tones (`"1"` to `"5"`, matching Bendy `Tone` raw
values), a tone prior, tolerances, one `unvoiced_ok` region (T3 creak), a list of commonly
confused tone pairs, and two accents with realisation rules: `cmn-standard` (Putonghua) and
`cmn-TW` (Taiwan Mandarin, inheriting from standard). The pack declares the `register`
capability. It is a table of expected tone shapes and tolerances. It contains no trained network
and no audio.

## Seed values only

**Every number in this pack is a seed. No parameter is fitted to data.** The tone shapes come from
published tone letters (Chao), and the realisation rules, mixture weights, tolerances, prior and
calibration constants (temperature 1.0, fusion weights, decode parameters) are hand-set starting
points from the design spec (§6.2). They are not tuned against any corpus, and the `cmn-TW`
realisation weights in particular are a seed for realisational differences only. Lexical
differences between accents come from the caller's lexicon, not from this pack.

Fitting happens in P1 against sources listed in `data-register.csv`. Synthetic or TTS audio is
never used to fit shipped calibration. The fitted pack gets its own `PROVENANCE.toml` entries and
a DJ audit of the tones, realisation rules and TW seed before it ships.

## Intended use

Grading a learner's syllable against **caller-supplied targets**: the caller states which tone
each syllable was meant to carry, in which accent, optionally with weighted lexical variants and
an optional style profile, and the pack turns that into the expected shape (a weighted mixture of
Chao contours with tolerances). Output built on it is a distance and a likelihood relative to
those targets, not a classification of the speaker.

## Out of scope

Out of scope (spec §11.3 to §11.5), and not to be built on this pack:

- Identifying a speaker's first language, dialect, region of origin or nativeness. Grading and
  accent fit are always relative to accents the caller names. Accent fit over a learner-chosen
  short list, on the learner's own audio, on-device, is inside the boundary. There is no
  operation that identifies an accent across all profiles.
- Speaker embeddings or voice modelling of any kind (spec §11.3, §11.4). Style profiles are
  per-tone mean contours in normalised pitch space, and the pack ships no profiles of named people.

## Known limitations

- Unfitted, so scores are only as good as the published-letter seeds. Expect miscalibrated
  likelihoods until P1.
- Five tones and two accents. Other Mandarin varieties are not modelled, and neither is tone
  sandhi beyond the listed realisation rules (for example T3+T3 becoming T2+T3): the caller
  resolves the target tone for the accent (spec §6.1).
- The neutral tone is realised from the previous syllable's tone. Its shape is context-dependent
  and varies more between speakers than the four full tones.
