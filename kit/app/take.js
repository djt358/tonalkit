// One recorded take -> the clip that's kept: resample to 16 kHz, trim the silent ends, encode.
import { resample, TARGET_RATE } from "./resample.js";
import { trim } from "./trim.js";
import { peakAbs } from "./level.js";
import { encodeWav } from "./wav.js";

const round = (x, digits) => Math.round(x * 10 ** digits) / 10 ** digits;

/**
 * @param {Float32Array} samples the take at the device rate
 * @param {number} rate the device rate (AudioContext.sampleRate)
 * @returns {{wav: Uint8Array, duration_s: number, peak: number, quiet: boolean}}
 */
export function processTake(samples, rate) {
  const { samples: kept, quiet } = trim(resample(samples, rate), TARGET_RATE);
  return {
    wav: encodeWav(kept, TARGET_RATE),
    duration_s: round(kept.length / TARGET_RATE, 3),
    peak: round(Math.min(1, peakAbs(kept)), 4),
    quiet,
  };
}
