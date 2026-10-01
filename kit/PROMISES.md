# Promises register

Every promise we make to volunteers, in [`CONSENT.md`](CONSENT.md), [`GUIDE.md`](GUIDE.md) and
[`copy.json`](copy.json), with the mechanism that keeps it and the test that fails if it breaks.
A promise with no mechanism doesn't go in the text.

How to read the status marks:

- `(built)`: it is in the repository now. `(built, as policy)`: it is written down and reviewed, not tested.
- `P4 (pending)`, `P5 (pending)`, `C0 (pending)`, `E1 (pending)`: that task builds it.
- `DJ (operational)`: no code can keep it; it is DJ's own routine. Read these twice.

`harness/tests/test_kit_promises.py` checks that every quotation below appears word for word in
the file it names, that every "never" in the consent has a row, and that the files named as
mechanisms exist. Change the wording of a promise and the test tells you to change this table.

| Promise | Where we say it | Mechanism that keeps it | Test |
|---|---|---|---|
| Your recordings stay on your phone until you send them. | CONSENT "Nothing leaves your phone until you tap Share."; GUIDE "They stay on your phone until you send them"; copy mic.body "Your recordings stay on your phone until you choose to share them." | The kit is a static page with no upload code, and its content-security policy allows no outbound connections. The only ways out are the share sheet and a saved file. P4 (pending). | P4 end-to-end test: after the page loads, a full session makes no network request. P4 (pending). |
| You agree before anything is recorded. | CONSENT "Tap **I agree** to begin." | The consent screen comes first and the microphone isn't requested until you agree. The bundle records the consent version and time (contracts §2). P4 (pending), C0 (pending). | P4 end-to-end test: no microphone request before "I agree". P4 (pending). C0 bundle-model test: a bundle without `consent` is rejected. C0 (pending). |
| Only what we list is recorded: no name, email or phone number, just a random code. | CONSENT "No name, email or phone number."; CONSENT "Recordings carry a random six-character code, not your name."; CONSENT "Your phone model and microphone settings, to check audio quality."; GUIDE "they carry a random code instead of your name" | The three background answers are taps on fixed options, and the kit has no free-text field P4 (pending). The bundle format allows only the enum fields in contracts §2 plus the device fields, and rejects any other field C0 (pending). Intake refuses a bundle with extra fields and names the speaker `v-<code>` P5 (pending). The code is six random characters made by the kit (contracts §2). | C0 bundle-model tests: an unknown or free-text field is rejected. C0 (pending). P5 intake test: same, at the door. P5 (pending). P4 unit test of the code's alphabet and length. P4 (pending). |
| You can pick Prefer not to say on the first two questions. | CONSENT "You can choose **Prefer not to say** on the first two."; copy background.intro "You can pick Prefer not to say on the first two." | `prefer_not` is a value of `background` and `grew_up_hearing` (contracts §2), and `copy.json` offers it for both (built). C0 (pending) enforces the enums. | `test_kit_copy.py`: `copy.json` has a label for every enum value, and for nothing else (built). C0 enum tests. C0 (pending). |
| Only your last take of each card is kept. | CONSENT "Only your last take of each card is kept." | The bundle holds `clips/<card id>.wav`, the last kept take only (contracts §2). P4 (pending). | P4 end-to-end test: record a card twice, export, find one clip with `takes` = 2. P4 (pending). |
| Only DJ gets your recordings, on DJ's computers and in a private cloud workspace. | CONSENT "It is analysed on DJ's own computers and in a private cloud workspace."; CONSENT "Nobody else." | All volunteer data lives in one place, the data root `$TONEKIT_DATA` (contracts §3), on DJ's machines and the private workspace. Who can open that workspace is DJ's own setting. DJ (operational). | None. A person keeps this one. |
| We never share your recordings with anyone else or send them to another service. | CONSENT "Share them with anyone else, or send them to any other service."; GUIDE "I'll never publish or share them" | There is no upload path in the kit (first row). The harness has no network client. Tencent SOE is used on DJ's own recordings only, never on volunteers' (spec §16, decision 5; register row `tencent-soe`) (built). | `test_kit_promises.py`: no file in `harness/src` imports a network client (built). Adding one means changing that test on purpose. |
| We never publish your recordings. | CONSENT "Publish your recordings." | Audio lives under `$TONEKIT_DATA`, outside the repository (contracts §3). `.gitignore` and `scripts/check-no-audio.sh` keep audio files out of git, and the CI job `no-audio` runs on every pull request and every push to main (built). | `scripts/check-no-audio.sh` (built). Gap: it doesn't cover `.zip` bundles yet (open items). |
| What we publish is overall results, never recordings. | CONSENT "We may publish overall results, such as how often the checker was right. Never your recordings." | No recordings in git (row above). The repository is public, so no speaker data goes in it either (contracts §3); per-speaker detail stays under `$TONEKIT_DATA`. DJ (operational): DJ reads each report before it is committed. | None for speaker data yet (open items). |
| We never use your recordings to identify you. | CONSENT "Use them to identify you." | tonekit ships no identification API or model and no speaker embeddings, and contributions that add one are refused (spec §11.3 and §11.5; README "Misuse boundary"; MODEL_CARD "Out of scope"; CONTRIBUTING "Scope limits"). Volunteers are pseudonymous (third row). (built, as policy) | None automated. Review holds the line. |
| We never clone or imitate your voice. | CONSENT "Clone or imitate your voice." | Voice modelling is out of scope (spec §11.4; README; MODEL_CARD; CONTRIBUTING), and the repository has no voice-modelling code. Volunteers default to the `gate` split, and fitting refuses `gate` speakers (contracts §3). (built, as policy). E1 (pending) for the refusal. | E1 test: fitting refuses a `gate` speaker. E1 (pending). The rest: none automated. |
| Your recordings are used to test the checker, not to tune it. | CONSENT "Your recordings test whether the checker works for real voices."; GUIDE "I only use them to test the app." | Register row `volunteer-corpus`: role gate and evaluation, calibration only after DJ confirms the consent wording, `shipped_weights_training` = `verify`. So `tkh provenance` fails any pack that lists it as a source without DJ's sign-off (built). Volunteers default to `gate`, and fitting refuses `gate` speakers E1 (pending). | `test_kit_promises.py`: a pack listing `volunteer-corpus` with no sign-off is a violation (built). E1 test (pending). |
| We delete your recordings, your answers and everything made from them when you ask. | CONSENT "We then delete your recordings, your answers and everything made from them."; GUIDE "I'll delete yours whenever you ask."; copy done.code_note "Keep this code if you ever want your recordings deleted" | `tkh purge --session CODE` (contracts §6). It removes the audio, the manifest rows, the speaker entry, the analysis-cache entries, the review pages that embed the audio, any bundle left in `inbox/`, and anything else intake wrote for that session. It logs the purge in `purge-log.jsonl`, marks the scoreboard and any calibration fitted on that corpus as stale, and is safe to repeat. P5 (pending). Then DJ deletes the original zip from Messages, Mail, AirDrop or Downloads. DJ (operational). | P5 purge tests: each item above is gone, the log line is written, a second run changes nothing, an unknown code says "nothing found". P5 (pending). The DJ step has no test. |
| We keep it until the project no longer needs it, or until you ask. | CONSENT "Until the project no longer needs it, or until you ask us to delete it." | None in code. DJ decides when the project no longer needs it, then purges every session. DJ (operational). | None. |
| Results already written up can't be redone, but they contain no audio. | CONSENT "Overall results already written up can't be redone, but they contain no audio." | This is a limit we state, not a promise. Purge marks outputs stale so the next run leaves you out (deletion row); written-up results stay as written. P5 (pending). | P5 purge test: the scoreboard is marked stale. P5 (pending). |
| Taking part is voluntary: skip any card or stop any time, and closing the page sends nothing. | CONSENT "Skip any card, or stop any time. Closing this page sends nothing."; copy pause.body "Your recordings so far are saved on this phone." | Any card can be skipped and a partial session is valid (the `skipped` list, contracts §2). Nothing is sent unless you tap Share (first row). Progress stays on the phone so you can resume. P4 (pending), P5 (pending). | P4 end-to-end test: skip a card, export, find it in `skipped`; close the page, no request. P5 test: intake accepts a partial bundle. P4 (pending), P5 (pending). |

## Open items

Not built yet, by task:

- **P4:** no outbound requests (content-security policy plus the test); consent first; no free-text
  field; the session code; skip, resume and last-take-only; the two end-to-end tests above.
- **C0:** the bundle model with enum-only speaker fields, the device fields, `consent` and extra
  fields rejected.
- **P5:** `tkh purge`; intake rejecting extra fields and accepting partial sessions; purge covering
  everything intake writes for a session. Contracts §6 doesn't list the intake's copy of
  `session.json` or its QC report; purge has to remove them too.
- **E1:** volunteer speakers default to `gate`; fitting refuses `gate` and `heldout` speakers.

DJ's routine, which no code keeps:

- Only DJ can open the private workspace and the data root.
- Keep no list linking session codes to people. A deletion request arrives as a code.
- After a purge, delete the original zip from wherever it arrived.
- Read each report before it is committed: no per-speaker rows in the public repository.
- Change the wording of `CONSENT.md` only with a new version line (`v2`), since every bundle
  records the version its speaker saw.

Gaps found while writing this register:

- `scripts/check-no-audio.sh` blocks audio file types but not `.zip`, and a volunteer bundle is a
  zip of WAV files. Add `zip` to the script and to `.gitignore`.
- Nothing scans tracked files for session codes or speaker ids. Reports are the likely place one
  would slip in.
- "Never identify you" and "never clone your voice" are policy, with no automated test.
