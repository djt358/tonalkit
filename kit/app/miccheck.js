// The microphone check: the person says a few words (mic.checking) for about three seconds.
// From the 50 ms level frames, the room is the quiet end (10th percentile) and the voice the
// loud end (90th percentile): a noisy room is still noisy while they talk, and a whisper or a
// covered microphone never gets loud.

export const MIC_CHECK_S = 3;
export const NOISY_FLOOR_DB = -45; // room level above this: "a bit noisy"
export const LOW_SPEECH_DB = -40; // voice level below this: "a bit quiet"
const FLOOR_P = 0.1;
const SPEECH_P = 0.9;

/** Nearest-rank percentile (p in [0, 1]) of `values`; -Infinity when there are none. */
export function percentile(values, p) {
  if (!values.length) return -Infinity;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1))];
}

/**
 * @param {number[]} levelsDb the check's level frames (dBFS RMS)
 * @returns {{verdict: "ok"|"noisy"|"low", floor: number, speech: number}}
 */
export function micVerdict(levelsDb) {
  const floor = percentile(levelsDb, FLOOR_P);
  const speech = percentile(levelsDb, SPEECH_P);
  const verdict = floor > NOISY_FLOOR_DB ? "noisy" : speech < LOW_SPEECH_DB ? "low" : "ok";
  return { verdict, floor, speech };
}
