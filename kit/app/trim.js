// Auto-trim: drop leading and trailing silence from a take by frame energy, keeping 150 ms of
// margin on each side. Only the two ends move: everything between the first and the last frame
// that sounds like speech is kept, pauses included.
import { rms, toDb } from "./level.js";

export const MARGIN_S = 0.15;
export const FRAME_S = 0.01;
export const QUIET_DB = -50; // a take whose loudest 10 ms is below this is "too quiet"
const ABOVE_FLOOR_DB = 10; // speech: at least this far above the take's own noise floor ...
const BELOW_PEAK_DB = 40; // ... or within this of its loudest frame, whichever is higher

/**
 * @param {Float32Array} samples
 * @param {number} rate
 * @returns {{samples: Float32Array, start: number, end: number, quiet: boolean}}
 *   `quiet`: nothing in the take reached QUIET_DB; such takes (and takes with no clear
 *   speech/silence contrast) are returned whole.
 */
export function trim(samples, rate) {
  const whole = { samples: samples.slice(), start: 0, end: samples.length };
  const frame = Math.max(1, Math.round(rate * FRAME_S));
  const count = Math.floor(samples.length / frame);
  if (count === 0) return { ...whole, quiet: true };

  const dbs = new Float64Array(count);
  for (let f = 0; f < count; f++) dbs[f] = toDb(rms(samples, f * frame, (f + 1) * frame));
  const sorted = Float64Array.from(dbs).sort();
  const peak = sorted[count - 1];
  const floor = sorted[Math.floor(count * 0.1)];
  if (peak < QUIET_DB) return { ...whole, quiet: true };

  const threshold = Math.max(floor + ABOVE_FLOOR_DB, peak - BELOW_PEAK_DB);
  let first = -1, last = -1;
  for (let f = 0; f < count; f++) {
    if (dbs[f] >= threshold) {
      if (first < 0) first = f;
      last = f;
    }
  }
  if (first < 0) return { ...whole, quiet: false };

  const margin = Math.round(rate * MARGIN_S);
  const start = Math.max(0, first * frame - margin);
  // The last frame may be followed by a partial one: count it as speech-adjacent, never cut it.
  const lastEnd = last === count - 1 ? samples.length : (last + 1) * frame;
  const end = Math.min(samples.length, lastEnd + margin);
  return { samples: samples.slice(start, end), start, end, quiet: false };
}
