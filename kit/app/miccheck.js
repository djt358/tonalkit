// The microphone check: the person says a few words (mic.checking) for about three seconds.
// From the 50 ms level frames, the room is the quiet end (10th percentile) and the voice the
// loud end (90th percentile): a noisy room is still noisy while they talk, and a whisper or a
// covered microphone never gets loud.

export const MIC_CHECK_S = 3;
export const NOISY_FLOOR_DB = -45; // room level above this: "a bit noisy"
export const LOW_SPEECH_DB = -38; // voice level below this: "a bit quiet"
const FLOOR_P = 0.1;
const SPEECH_P = 0.9;
// iOS can deliver digital silence for the first frames while the microphone warms up: those
// would read as a very quiet room (or a covered microphone), so they are not counted, as long as
// a second of real frames remains.
export const WARMUP_FRAMES = 4;
const MIN_FRAMES_AFTER_WARMUP = 20;

/** Nearest-rank percentile (p in [0, 1]) of `values`; -Infinity when there are none. */
export function percentile(values, p) {
  if (!values.length) return -Infinity;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1))];
}

/**
 * @param {number[]} allLevelsDb the check's level frames (dBFS RMS), warm-up included
 * @returns {{verdict: "ok"|"noisy"|"low", floor: number, speech: number}}
 */
export function micVerdict(allLevelsDb) {
  const levelsDb =
    allLevelsDb.length >= WARMUP_FRAMES + MIN_FRAMES_AFTER_WARMUP ? allLevelsDb.slice(WARMUP_FRAMES) : allLevelsDb;
  const floor = percentile(levelsDb, FLOOR_P);
  const speech = percentile(levelsDb, SPEECH_P);
  const verdict = floor > NOISY_FLOOR_DB ? "noisy" : speech < LOW_SPEECH_DB ? "low" : "ok";
  return { verdict, floor, speech };
}

// The live check: people start talking a beat after they read the prompt, and speak up when told
// they're quiet, so one verdict after a fixed three seconds misleads both ways. Instead the
// verdict is re-read over the last few seconds while the screen is open: "a bit quiet" only after
// SPEECH_WAIT_S without a voice loud enough, "that sounds good" as soon as one is heard (and it
// stays, so a pause after speaking doesn't bring "quiet" back), "noisy" whenever the room is.
export const WINDOW_FRAMES = 60; // the last 3 s of 50 ms frames
export const SPEECH_WAIT_S = 6;

/**
 * @param {number[]} allLevelsDb every level frame since the check started, warm-up included
 * @param {number} elapsedS seconds since the check started
 * @param {boolean} heard whether a loud-enough voice has been heard already
 * @returns {{verdict: "checking"|"ok"|"noisy"|"low", floor: number, speech: number, heard: boolean}}
 */
export function liveVerdict(allLevelsDb, elapsedS, heard = false) {
  const usable = allLevelsDb.slice(Math.min(WARMUP_FRAMES, Math.max(0, allLevelsDb.length - MIN_FRAMES_AFTER_WARMUP)));
  const window = usable.slice(-WINDOW_FRAMES);
  const floor = percentile(window, FLOOR_P);
  const speech = percentile(window, SPEECH_P);
  if (window.length < MIN_FRAMES_AFTER_WARMUP) return { verdict: "checking", floor, speech, heard };
  const nowHeard = heard || speech >= LOW_SPEECH_DB;
  const noisy = floor > NOISY_FLOOR_DB;
  if (nowHeard) return { verdict: noisy ? "noisy" : "ok", floor, speech, heard: true };
  if (elapsedS < SPEECH_WAIT_S) return { verdict: "checking", floor, speech, heard: false };
  return { verdict: noisy ? "noisy" : "low", floor, speech, heard: false };
}
