# Tone assessment: prior art and gap analysis

**Date:** 2026-09-28 · **Feeds:** `docs/superpowers/specs/2026-09-28-tone-assessment-design.md`
**Consumers:** Bendy (pronunciation practice, `pinyinRecall`) and proj-xiuzhen (cast gate)
**Companion data:** `tone-assessment-license-register.csv` (machine-readable license and provenance list)

---

## 0. The short answer to "surely some Chinese OSS model can hear tones?"

Yes, and that is part of the problem.

- **Native tone perception is effectively solved inside ASR.** A wav2vec2 system that decodes
  audio → toned pinyin → hanzi reaches a **2.5% Pinyin+Tone error rate** on AISHELL-1, against
  2.0% for toneless pinyin. Tone adds half a point of error ([Decoupling recognition and
  transcription in Mandarin ASR](https://arxiv.org/pdf/2108.01129)). SSL models trained only on
  audio already encode tone in their representations, and tonal-language pretraining strengthens
  it ([Encoding of lexical tone in SSL models](https://arxiv.org/html/2403.16865v2)).
- **But these systems hear tone in order to discard it.** An ASR model uses tone as evidence for
  the character, and its language model then corrects the character. A learner who says 睡 when
  they meant 水 gets 水 back in a sentence about drinking. Audio LLMs are worse: across 12 models,
  outputs matched a misleading transcript **64% of the time** and the acoustic ground truth
  **15% of the time**. GPT-4o Audio followed the false transcript in 81.6% of cases
  ([VoxParadox](https://arxiv.org/html/2605.27772v1)).
- **Speech-LLM tokenizers throw tone away.** Discrete speech units lose a lot of tone
  information even when they come from Mandarin-specialised SSL models
  ([Do discrete SSL representations capture tone?](https://awesomepapers.io/speech-audio/papers/2410.19935),
  [Lexical tone is hard to quantize](https://awesomepapers.io/speech-audio/papers/2604.07467)).
  On MMSU, the best model scores 53.6% on phonological perception against 94.3% for humans
  ([MMSU](https://arxiv.org/html/2506.04779v2)). So Qwen-Audio, Step-Audio, Kimi and similar
  models can't be dropped in as graders.
- **China does grade tone by machine, but the systems are closed.** Three of the four sections
  of the national Putonghua proficiency test (monosyllables, polysyllabic words, passage reading)
  are scored by a certified computer-assisted system, and humans score only free speech
  ([PSC computer-assisted scoring rules](https://putonghuaceshi.com/policy_details/402.html)).
  iFlytek ISE, Tencent SOE (with explicit 声调评测), SpeechSuper and Chivox all sell cloud APIs.
  None of them is open or on-device.

**The gap:** an open, permissively licensed, on-device grader that diagnoses L2 tone. It needs to
report what was produced relative to a known target, and it must not language-model its way
past errors. The perception half is well covered by existing work. The grading half is the part
we have to build.

---

## 1. Pitch (f0) tracking — commodity; slot in prior art

| Tracker | Type | License | Notes for us |
|---|---|---|---|
| **pYIN** (librosa; `pyin-rs` in Rust) | classical + HMM | ISC / **MIT** | Voicing probability per frame; `pyin-rs` ships a Rust lib and C ABI with a librosa-parity design ([pyin-rs](https://github.com/Sytronik/pyin-rs)) |
| **SwiftF0** (2025) | CNN on spectrogram | **MIT** | 16 kHz, 256 hop, 46.9–2093.8 Hz, ONNX; 132 ms for 5 s of audio on CPU ([repo](https://github.com/lars76/swift-f0), [paper](https://arxiv.org/abs/2508.18440)) |
| CREPE / torchcrepe | CNN | MIT | Accurate but slow; noisy-speech accuracy falls 79.7% → 53.8% on PTDB-Noisy ([benchmark](https://github.com/lars76/pitch-benchmark)) |
| PENN | CNN | MIT | Best on PTDB-Noisy (76.4%) in that benchmark |
| RMVPE / FCPE | CNN | varies by fork | Built for singing and polyphonic music (RVC/so-vits ecosystem); not needed for solo speech |
| PESTO | SSL, streaming | **LGPL-3.0** | Excluded: LGPL is awkward for static linking on iOS ([pesto-full](https://github.com/SonyCSLParis/pesto-full)) |
| Praat / Parselmouth | classical | **GPL-3.0** | Excluded from shipped code; fine as a researcher's eyeball tool |

In the [pitch-benchmark](https://github.com/lars76/pitch-benchmark) (MIT), SwiftF0 has the best
overall average (90.2%) and degrades least under noise among the fast options (90.4% → 74.0% on
PTDB → PTDB-Noisy). Praat runs at 2.8 ms per second of audio with 84.7% accuracy.

**Takeaway:** don't build a pitch tracker. Ship pYIN in the Rust core as the dependency-free
default, and bake off SwiftF0 converted to CoreML on DJ's café-noise corpus in P0.

## 2. Syllable alignment — mostly commodity

- **Known syllable count.** Bendy and xiuzhen always know the target, so segmentation is a
  constrained alignment over energy, voicing and spectral change with N fixed. No model needed
  for P0.
- **Recognizer timings.** `SFSpeechRecognizer` segments carry timestamps and durations, and
  iOS 26 `SpeechAnalyzer`/`SpeechTranscriber` return per-token timing and confidence
  ([overview](https://blakecrosley.com/blog/speech-framework-vs-sfspeechrecognizer)). When the
  transcript matches the target, these are free alignment evidence. Mandarin locale support for
  `SpeechTranscriber` wasn't confirmed and has to be checked at build time.
- **Forced aligners.** The Montreal Forced Aligner Mandarin v3.0.0 acoustic model is **CC BY 4.0**
  and was trained on Common Voice zh, AISHELL-3, THCHS-30, AI-DataTang and GlobalPhone
  ([MFA Mandarin](https://mfa-models.readthedocs.io/en/latest/acoustic/Mandarin/Mandarin%20MFA%20acoustic%20model%20v3_0_0.html)).
  *Update (spec v2.2):* AISHELL/THCHS are now plain Apache-2.0 (see §3.2), but it was also trained
  on AI-DataTang (license unconfirmed), so it stays `verify`. It isn't needed in P0. Meta **MMS models,
  including torchaudio's MMS_FA and wrappers like `torchfa`, are CC-BY-NC 4.0**, so they are
  excluded ([MMS README](https://github.com/facebookresearch/fairseq/blob/main/examples/mms/README.md),
  [torchfa](https://github.com/pengzhendong/torchfa)).

## 3. Mandarin tone recognition and L2 assessment

### 3.1 Academic

| Work | What it shows | Relevance |
|---|---|---|
| ToneNet (Interspeech 2019) | CNN on mel-spectrograms classifies isolated syllables at high accuracy | Isolated native syllables are the easy case |
| [Pitch-aware RNN-T MDD](https://www.isca-archive.org/interspeech_2024/wang24la_interspeech.pdf) (Interspeech 2024) | On L2 tone errors: **precision 0.111, recall 0.922, F1 0.198**. Adding f0 cut PER 16% and raised F1 31%. Calls LATIC "the only publicly available L2 Mandarin dataset for training" | End-to-end L2 tone MDD is not solved. Explicit pitch helps even big models |
| [Phonological-level wav2vec2 MDD](https://arxiv.org/html/2606.22022) (2026) | Represents tones as **pitch-target attributes** (onset/offset levels) rather than categories, cutting diagnostic error about 12%. High-offset (T1/T2) attributes are hardest | Supports a descriptor-first, language-agnostic representation |
| [Siamese ResNet tone scorer](https://www.nature.com/articles/s41598-025-08544-8) (Sci. Rep. 2025) | Normalises contours to the **five-degree (Chao) scale** and learns pairwise tone distance. RMSE 1.515 against expert scores. Trained on THCHS-30 and AISHELL-1/2/3 plus a private L2 set | Grading as distance to a reference in Chao space, the same idea as xiuzhen's "distance, not classification" |
| [Tone value representation for CAPT](https://www.isca-archive.org/speechprosody_2024/li24e_speechprosody.html) (Speech Prosody 2024) | Normalises contours for coarticulation and phrasing. Learners identify tones from the plot, and the plot gives richer feedback than a recognizer label | Visual feedback should show normalised contours, not raw Hz. *Only the abstract was read; the full text was rate-limited.* |
| [Interpretable L2 tone review](https://www.mdpi.com/2227-7390/14/1/145) (2026) | **T2/T3 is the persistent L2 confusion.** Learners diverge in slope, turning-point timing and range. Recommends reporting those parameters, e.g. "advance the peak by ~80 ms" | Defines our diagnostic vocabulary |
| [Perceptual compensation in SSL models](https://arxiv.org/html/2606.17835) (2026) | Pretrained wav2vec2 shows **no** compensation for preceding-tone context. Fine-tuned models show only weak effects | Coarticulation context must be modelled explicitly. A big encoder won't learn it for free |
| qTA / PENTA ([Xu](http://www.homepages.ucl.ac.uk/~uclyyix/qTA/)) | Tone as a pitch target approached with some strength, parameterised by height, slope and strength. Applied well beyond Mandarin | A mature language-agnostic parameterisation, held as a P3 option |

### 3.2 Open data (the binding constraint)

- **Native, permissive:** AISHELL-1 (Apache-2.0), **AISHELL-3 (Apache-2.0, 85 h, 218 speakers,
  character and pinyin transcripts)**, THCHS-30 (Apache-2.0), Common Voice zh-CN (CC0).
  OpenSLR also said "free for academic use" next to Apache-2.0 on the AISHELL and THCHS pages.
  *Update (spec v2.2):* DJ confirmed that caveat has been rescinded and both are plain Apache-2.0.
  AISHELL-3 is the primary native calibration source.
- **Native, but excluded from shipped weights:** MagicData read speech (**CC BY-NC-ND**), KeSpeech
  (**non-commercial custom**), WenetSpeech (CC BY 4.0 labels, but audio scraped from
  YouTube and podcasts behind a password-gated license), Tone Perfect (**"In Copyright –
  Educational Use Permitted"**, non-commercial access only;
  [Tone Perfect story](https://ideah.pubpub.org/pub/hh90jpsu)).
- **L2 Mandarin, open:** LATIC (4 h, 4 speakers with Russian, Korean, French and Arabic L1,
  "any purpose"; [IEEE DataPort](https://ieee-dataport.org/open-access/latic-non-native-pre-labelled-mandarin-chinese-validation-corpus-automatic-speech))
  and **OMPAL** (1,768 utterances, French L1, word- and sentence-level expert scores, "commercial
  and non-commercial use";
  [Interspeech 2025](https://www.isca-archive.org/interspeech_2025/hsieh25b_interspeech.html)).
  Neither has per-syllable tone labels. iCALL (European L1s) is restricted.

**Takeaway:** there isn't enough permissively licensed L2 data to train an end-to-end grader.
There is plenty of permissive native data to learn what correct tones look like, and a distance
from correct is exactly what xiuzhen's scoring contract asks for.

### 3.3 Chinese OSS speech stacks

| Stack | License | Tone output? |
|---|---|---|
| FunASR / Paraformer / SenseVoice | Code MIT; model license custom. Maintainers confirm commercial use is OK with attribution ([issue #334](https://github.com/QwenAudio/SenseVoice/issues/334)) | Hanzi only |
| k2 / icefall / **sherpa-onnx** | **Apache-2.0**, with iOS Swift and SwiftUI examples ([repo](https://github.com/k2-fsa/sherpa-onnx)) | Hanzi, plus KWS. A good runtime if we ever need an on-device CTC model |
| WeNet | Apache-2.0 | Hanzi |
| Qwen2-Audio / Qwen2.5-Omni etc. | various | No tone output; transcript-following (§0) |
| pypinyin | MIT; has `contrib/tone_sandhi.py` ([source](https://github.com/mozillazg/python-pinyin/blob/master/pypinyin/contrib/tone_sandhi.py)) | Text → toned pinyin, for authoring tools only |
| g2pW (via pypinyin-g2pW) | Apache-2.0 | Polyphone disambiguation for authoring |

### 3.4 Commercial graders (audit-only candidates)

| Service | Mandarin tone detail | On-device? |
|---|---|---|
| Azure pronunciation assessment | zh-CN has accuracy, fluency and completeness; phonemes in SAPI form with tone numbers. **Prosody assessment, syllable groups and NBestPhonemes are en-US only** ([docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment)) | No |
| Tencent SOE (新版) | Explicit 声调评测; pinyin mode detects tone for up to 4 syllables ([PDF](https://main.qcloudimg.com/raw/document/product/pdf/1774_107334_cn.pdf)) | No |
| SpeechSuper | "Tone prediction", single characters only as announced ([post](https://medium.com/@speechsuper1024/unveiling-speechsupers-tone-prediction-feature-for-improved-mandarin-chinese-pronunciation-2b6c2e30e3cb)) | No |
| iFlytek ISE | Powers PSC machine scoring | No |

**Implication for the existing xiuzhen spec:** Azure can say a syllable scored low but can't say
*which tone was produced*. Tencent SOE's pinyin mode is the better independent tone auditor for
the calibration harness. The spec updates the audit role to match.

### 3.5 Pedagogical tools

- **SpeakGoodChinese (SGC3)** uses Praat-based tone feedback and is **GPL-3.0**
  ([repo](https://github.com/robvanson/sgc3)). It's a useful UX reference, but its code can't be
  used.
- **Own-voice prosody transplantation** (replaying the learner's own voice with native pitch) is
  an established CAPT idea ([Transplanting native prosody](https://www.researchgate.net/publication/262943610_Transplanting_native_prosody_into_second_language_speech);
  self-imitation training, [MDPI 2024](https://www.mdpi.com/2226-471X/9/1/33)). It needs only
  the target contour and DSP, not a per-language output model.

## 4. Beyond Mandarin — what the typology demands of a "generic" layer

| Language (ISO 639-3) | Tone system | Why f0-only or Mandarin-shaped designs break | Open resources |
|---|---|---|---|
| **Cantonese (yue)** | 6 tones (9 counting entering tones), several distinguished **by level alone** (55/33/22) | Needs good **speaker-register normalisation**. Contour shape can't separate level tones | Common Voice yue / zh-HK (CC0). MDCC is **research-only** ([repo](https://github.com/HLTCHKUST/cantonese-asr)). [CantoASR](https://arxiv.org/pdf/2511.04139) feeds speaker-normalised f0, slope and duration bins from Parselmouth into Qwen2-Audio, the same "descriptors → language head" shape we propose |
| **Thai (tha)** | 5 tones; tone is predictable from spelling | Targets come from text. PyThaiNLP `tone_detector(syllable)` returns l/m/h/r/f ([docs](https://pythainlp.org/dev-docs/api/util.html)) | Common Voice th (CC0). PyThaiNLP (Apache-2.0) |
| **Vietnamese (vie)** | 6 tones; **ngã and nặng are glottalised or creaky** in the North | Northern listeners rely heavily on **voice quality**. Southern listeners rely mostly on f0 ([Brunelle 2009](https://sciencedirect.com/science/article/abs/pii/S0095447008000454)). Needs a phonation channel, and pitch dropout is a cue, not noise ([creak in Vietnamese](https://sites.google.com/ucsd.edu/yaqianhuang/research/creaky-voice-in-vietnamese)) | Common Voice vi (CC0, small). VIVOS is non-commercial (verify) |
| **Yorùbá (yor)** | 3 register tones (H/M/L) with **downdrift and downstep** | Needs utterance-level declination modelling. Current transformer ASR gets *worse* with tone-marked targets ([LoResLM 2026](https://aclanthology.org/2026.loreslm-1.14/)) | Common Voice yo (~6 h). **DunDun** reads tone targets from diacritics and scores f0 without a reference, which is our architecture applied to TTS ([Tone on a Budget](https://arxiv.org/abs/2609.14817), code released; *only the abstract was read*) |
| **Japanese (jpn)** | Pitch accent: H/L per **mora**, with an accent nucleus | The tone-bearing unit is the mora, not the syllable, and the melody is word-level | tdmelodic generates an accent dictionary (**BSD-3**, [repo](https://github.com/PKSHATechnology-Research/tdmelodic)). [onchou](https://github.com/bagustris/onchou) is a browser pitch-accent trainer with the same compare-to-target loop |
| Hmong, Burmese, Min, Wu | phonation plus contour; sandhi circles and tone spreading | Target generation (sandhi) is a large per-language job | Out of scope. Named here so the schema doesn't preclude them |

**Cross-language transfer evidence:** in SSL probing, a Cantonese-pretrained model performs on
Vietnamese tone about like an English-pretrained model
([Tilburg 2024](https://arxiv.org/html/2403.16865v2)). Tone knowledge in large encoders doesn't
transfer well between tone languages. What does transfer is the **measurement** (f0, voicing,
voice quality, normalisation, timing). That argues for sharing the measurement layer and keeping
the categories per language.

## 5. Licensing and safety findings (detail in the spec, §9)

1. **The code can be MIT OR Apache-2.0 with no material concern found.** Apache-2.0 adds an
   express patent grant that MIT lacks. Dual licensing gives downstream users the choice. An early
   tone-feature patent, US6829578B1 ("Tone features for speech recognition", Philips, 1999
   priority), is listed as **expired** (fee-related, 2022) on
   [Google Patents](https://patents.google.com/patent/US6829578B1/en). The techniques used (YIN 2002, pYIN 2014, Chao tone letters 1930,
   template distance) are long published. **No freedom-to-operate search was done.** Revisit
   before a funded launch.
2. **The material risk is in the weights and data, not the code.** Excluded sources:
   MMS (CC-BY-NC), MagicData (NC-ND), KeSpeech (NC), MDCC (research only), Tone Perfect
   (educational only), WenetSpeech (scraped audio), PESTO (LGPL), Praat, Parselmouth and SGC3
   (GPL). Each shipped weights file needs a provenance manifest that CI checks.
3. **Voice privacy.** Under Illinois BIPA a "voiceprint" is a pattern "for the purpose of
   identifying an individual speaker". Courts are split on whether non-identifying voice
   processing is covered ([MoFo](https://www.mofo.com/resources/insights/240503-getting-bipa-right-biometric-identifiers-must-identify)),
   and 2025–26 has seen new voiceprint class actions against AI transcription and training
   ([ABA](https://www.americanbar.org/groups/litigation/resources/newsletters/class-actions-derivative-suits/voiceprints-ai-bipa-new-trends-biometric-privacy-litigation/)).
   Design response: on-device only; no speaker embeddings; persist only a coarse pitch-range
   summary; raw audio discarded by default; any audio donation gets its own opt-in consent.
4. **Misuse surface.** A tone grader is a small step from a nativeness or origin profiler (the
   language-analysis-for-origin problem). Scope the API to grading against a supplied target, ship
   no L1, dialect or nativeness classifiers, and say so in the README.
5. **Honesty risk from the UI.** Standard-but-regional variants, such as Taiwan Mandarin's
   sparser neutral tone and Southern accents, must not be graded as errors. Bendy's
   `AccentProfile` tolerance model (feat-variants) has to reach the tone targets.

## 6. What this means for the build decision

| Piece | Build or borrow | Prior art to slot in |
|---|---|---|
| f0 and voicing | **Borrow** | pYIN (`pyin-rs`, MIT), SwiftF0 (MIT) behind a provider trait |
| Syllable alignment | **Borrow + thin glue** | Known-N DP; recognizer timings; MFA (CC BY) offline for labelling |
| Transcript evidence | **Borrow** | `SFSpeechRecognizer` / `SpeechAnalyzer` + Bendy's audited confusion sets |
| Tone targets from text | **Borrow** (authoring side) | Bendy lexeme data (audited); pypinyin, g2pW, PyThaiNLP, tdmelodic |
| **Normalised tone descriptors** | **Build** (the reusable core) | Chao scale, pitch-target attributes, qTA as a later option |
| **Per-language packs + calibrated scorer** | **Build** (thin) | Templates from AISHELL-3 means; DJ-audited |
| **Evidence fusion + calibration** | **Build** (small) | Logistic fusion; nothing off the shelf fits |
| Eval harness + provenance CI | **Build** | cargo-deny; manifest checks |
| Independent audit | **Borrow** (offline only) | Tencent SOE pinyin mode > Azure for tone |
| Output audio | **Borrow + DSP** | Pre-rendered audited native clips; own-voice pitch correction |

---

### Sources not read in full

- "Tone on a Budget" (arXiv 2609.14817) and "Tone Value Representation for CAPT" (Speech
  Prosody 2024): full text was rate-limited, so only the abstracts were used.
- "Tone recognition of continuous Cantonese speech based on SVMs" (ResearchGate): rate-limited,
  so no accuracy figure is cited.
- The iFlytek PSC news page failed its TLS handshake, so the PSC claim rests on the published
  scoring rules instead.
