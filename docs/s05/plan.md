# tonekit S0.5: everything S1 needs except the recordings, and the engine

*2026-10-01. Status: in progress. Runs Thursday to Monday around the weekend's volunteer
recordings. The formats are in [`contracts.md`](contracts.md).*

## Goal

When the weekend's recordings land, **one command gives the S1 verdict**, with every step before
it already built and tested:
- a guide and recording kit people can use without knowing why the project exists;
- consent;
- intake;
- per-speaker grading;
- review;
- the gate.

The S1 questions that don't need those recordings get answered on public native speech first.

The same machinery is the **engine** that runs P1…Pn: each later phase is a new corpus plus a gate
file, not a new pipeline.

## The engine

```
iPhone kit ─▶ zip via share sheet ─▶ tkh intake ─▶ corpus registry ─▶ tkh score ─▶ tkh gate <id> ─▶ tkh review ─▶ decision
                                      (validate,     ($TONEKIT_DATA:     (every corpus,  (gates/*.toml)     (listen,
                                       QC, codes)     splits, provenance) every metric)                     relabel)
```

- **Data in.** Every source enters through `tkh intake` (volunteer bundles) or a corpus adapter
  (AISHELL-3 or THCHS-30, Common Voice).
  - Each source lands under `$TONEKIT_DATA`, never in the repo.
  - Speakers get splits: `gate`, `dev`, `calib` or `heldout`.
  - Selections compose across corpora: volunteer and DJ gate speakers together, public `calib`
    with volunteer `gate`, and so on.
  - Anything that fits parameters refuses the `gate` and `heldout` speakers, and gates refuse
    synthetic data.
- **Gates as data.** `gates/s1.toml`, `p1.toml` and `p2.toml` hold the metrics, selectors,
  thresholds and minimum speakers/L1s.
  - `tkh gate p1` already runs: it lists the inputs still missing.
  - P2's "no diff outside `packs/`" is a check in its gate file.
- **Scoreboard.** `tkh score` runs every registered corpus through the current build. A baseline
  of the in-repo synthetic and fixture set lives in git, and Linux CI fails on a regression.
- **Review.** `tkh review` writes a listening page for gate failures and adversarial finds. Its
  relabel patch applies with `tkh relabel`, with an audit trail.
- **Promises kept by code.** Every promise in the consent text maps to a mechanism and a test in
  `kit/PROMISES.md`:
  - "never published": the no-audio CI check and the data root outside the repo;
  - "deleted on request": `tkh purge --session CODE` removes the audio, manifest rows, cache
    entries and review pages, logs the purge, and marks fits as stale;
  - "no names": session codes and enum-only metadata.
- **Process.**
  - Each phase has a one-page charter in `docs/phases/`.
  - Checkpoints are PRs into `main`. Each carries CI and the scoreboard diff in its description,
    and merges once its review is clean, so you can read them after the fact.
  - The rate-limit waves are unchanged.
  - While n is small, intake is run by hand when files arrive.

## Decisions (DJ, 2026-10-01)

1. **Volunteers record on their own iPhones**, in Safari, on the kit's page (GitHub Pages). They
   send the exported zip to DJ through the share sheet.
   - **Why a web page and not Voice Memos:** it records each card as its own clip, keeps iOS voice
     processing off, and exports 16 kHz WAV plus `session.json`. There is no manual splitting and
     no manifest writing.
2. **Volunteers are trusted, known people.** Files go straight to DJ, with no hosted upload.
3. **Deliberate errors: yes**, as "read it exactly as written" cards (一杯睡 for 一杯水).
4. **About 20 minutes and about 70 cards per person.** DJ still records the full set.
5. **Sandhi vs "solitaire" (citation reading) is critical.**
   - The deck carries both contexts: 一 alone (yī), 一杯 (yì), 一块 (yí); 不 alone (bù), 不对 (bú);
     水 (shuǐ), 水果 (shuí guǒ).
   - Every card states its context. The deck builder checks surface tones against the sandhi rules.
   - Reports break results down by context.
6. **Public corpora are downloaded by DJ.** S0.5 and S1 compose those with the recorded sets
   through the registry.
7. **Data promises are kept by mechanism** (purge, provenance, no names, never published) without
   enterprise process. Not missing a tick is the bar.

## Lanes and tasks

| ID | Task | Delivers | Depends on | Size |
|---|---|---|---|---|
| **W0** | **Safety and contracts (controller)** | | | |
| 0.1 | Audio can't be committed | `.gitignore` rules, `scripts/check-no-audio.sh`, CI `no-audio` job | — | done |
| 0.2 | Contracts written | `contracts.md` | — | done |
| C0 | Contracts as code | `tonekit_harness/contracts/{deck,bundle,registry,gate}.py` with validators per `contracts.md`; manifest additions; `tkh schema` (JSON Schema to `kit/schema/`); tests | 0.2 | M |
| **P** | **Participant kit (weekend critical path)** | | | |
| P1 | Lay guide plus all in-kit copy. Two reading modes. Not condescending, no jargon | `kit/GUIDE.md`, `kit/copy.json` | 0.2 | S |
| P2 | Plain-language consent; `volunteer-corpus` register row; the promises register | `kit/CONSENT.md`, `kit/PROMISES.md`, register row, DATA_PROVENANCE note | — | S |
| P3 | Deck v1 + builder + sandhi checker: gate pairs (g_measure), error cards, register, minimal pairs, count cards, phrase/isolated contrasts. All cards `unverified` until DJ audits | `kit/deck/s05-v1.toml`, `tkh deck check`, sandhi tests | C0, g_measure CSV (a stand-in draft until it arrives) | M |
| P4 | iPhone web kit (details below), tested in headless Chromium with a WAV fake microphone; GitHub Pages deploy workflow | `kit/` (static), e2e test, `.github/workflows/pages.yml` | 0.2, C0 schemas | L |
| P5 | `tkh intake ZIP...`: validate against the deck, QC (clipping, SNR, silence, length), speaker entry `v-<code>`, accent from `grew_up_hearing`, manifest rows, QC report; `tkh purge --session CODE` | intake + purge + tests | C0, E1 | M |
| P6 | Dress rehearsal (Fri): DJ records 6 cards on an iPhone → share → intake → score → gate (smoke) → review | rehearsal notes + fixes | P4, P5, E2–E4 | S |
| **R** | **Read real speech now** | | | |
| R1 | Fluent-speech readiness: contiguous and coarticulated testkit speech (0–20 ms gaps, 4–6 syllables/s, glides, octave-spanning registers); fix segmentation or octave repair if the sweep fails | sweep in CI + fixes + ruling | — | L |
| R2 | Multi-speaker gate: per-speaker register and accent; leave-one-speaker-out thresholds; pooled and per-group S1; breakdowns by speaker, background and context | eval/metrics/report | C0 | M |
| R3 | Corpus adapters (AISHELL-3 or THCHS-30, CV zh-CN and zh-TW) into the registry, with hashed speaker splits | adapters + tests on tiny fake corpora | E1, DJ download | M |
| R4 | S1-proxy on native audio: true reading vs every single-tone substitution, leave-one-speaker-out; candidate-ID, per-tone confusion, native tone-ID floor (spec §13) | `reports/s05-native.md` | R2, R3 | M |
| R5 | Fail-path spike (research only): permissively licensed SSL tone evidence, register rows (`verify`), the `Evidence::Neural` hook | memo + rows | — | S |
| **E** | **Engine** | | | |
| E1 | Data root + registry: load and select (compose across corpora), split refusal, staleness markers | `tonekit_harness/registry.py` + tests | C0 | M |
| E2 | `gates/{s1,p1,p2}.toml` + `tkh gate ID`: verdict md and JSON, or INCOMPLETE listing missing inputs | gate runner + tests | C0, E1, R2 | M |
| E3 | `tkh score` scoreboard + committed baseline + Linux CI regression check | scoreboard + CI | E1 | M |
| E4 | `tkh review` listening page + `tkh relabel` with an audit trail | review loop + tests | C0 | M |
| E5 | `docs/phases/` charter template, S0.5 and P1 charters, PR template carrying the scoreboard diff | docs | E3 | S |

**Alongside, if budget remains:** faster pYIN (R52), which is P1's first task.

### P4: the kit on an iPhone

- Static HTML, CSS and JavaScript with no build step, served by GitHub Pages. Its host is HTTPS,
  which iOS Safari needs for microphone access.
- **Flow:** consent → three tap-to-answer background questions → microphone and room check (level
  meter, "a bit noisy" warning) → cards one at a time (record, play back, redo, skip) → done screen
  with the session code → **Share** (Web Share API with the zip; fallback: download to Files).
- **Capture:**
  - `getUserMedia` with `echoCancellation`, `noiseSuppression` and `autoGainControl` all false, and
    the actually applied settings recorded.
  - WebAudio capture at the device rate, then low-pass and resample to 16 kHz, saved as 16-bit
    mono WAV per card.
  - Recording is press-to-start and press-to-stop. A short auto-trim removes leading and trailing
    silence, keeping 150 ms of margin.
- **Robustness:** progress is kept in the page's storage, so a closed tab resumes where it left off.
  Nothing leaves the phone except through the share sheet.
- **Tests:**
  - Headless Chromium with `--use-file-for-fake-audio-capture` plays the fixture as the microphone.
  - The test records three cards, exports the zip and runs `tkh intake` on it.
  - The resampler has a unit test with a sine sweep.

## Waves

Each wave is sized to about 1.4M subagent tokens per 5-hour window.

| Wave | When | Units | Exit |
|---|---|---|---|
| W0 | Thu 01:30 | 0.1, 0.2 (done) → PR | `no-audio` job green |
| W1 | Thu | C0, P1+P2, P4, R1 in parallel; then P3, E1 | contracts in code; the kit records and exports in headless Chromium; fluent-speech sweep result |
| W2 | Thu–Fri | P5, R2, E2, E3, E4; DJ audits P1–P3 → deck v1 approved | `tkh gate s1` end to end on synthetic bundles; Pages URL live |
| W3 | Fri | P6 rehearsal + fixes; kit link and guide to DJ | **kit ready for the weekend** |
| W4 | Sat–Sun | R3, R4 (after download), R5, E5; pYIN speed if budget remains | native S1-proxy report |
| W5 | Mon | intake all bundles → `tkh gate s1` → `tkh review` → DJ listens → decision | S1 verdict + `p0-decision.md` |

## Waits for the recordings or for S1

- Calibration fit on gate speakers.
- Apple n-best rescoring.
- The tuned adversary search (CMA-ES).
- The `tkh critic` checks on TTS reference audio.
- Feedback-text wording.
- New lects.

## DJ to-dos

- **g_measure CSV:** send it; the gate cards come from its `spoken_pinyin` column.
- **Audits:** P1, P2 and the deck.
- **Pages:** enable GitHub Pages with "Source: GitHub Actions", unless the API call in P4 can do it.
- **Downloads:** AISHELL-3 (or THCHS-30) plus CV zh-CN and zh-TW subsets.
- **Rehearsal:** the six-card run on Friday.
