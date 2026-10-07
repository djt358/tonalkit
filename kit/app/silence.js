// A take with nothing in it is not kept. iOS can hand over zeros (a route change, an
// interruption) or a microphone that hears nothing; a volunteer cannot tell, and the clip would
// only spoil the set. Judged on the take as captured, before trimming.
import { frameDbs } from "./level.js";

export const SILENT_DB = -55; // a take whose loudest 50 ms is below this is refused
export const SILENT_FRAME_S = 0.05;

/**
 * Digital silence (all zeros) reads as -120 dBFS, so it is refused too. A take shorter than one
 * frame has no frame to be loud in and is refused.
 * @param {Float32Array} samples the take at the device rate
 * @param {number} rate the device rate
 * @returns {boolean}
 */
export function isSilentTake(samples, rate) {
  const frame = Math.max(1, Math.round(rate * SILENT_FRAME_S));
  let loudest = -Infinity;
  for (const db of frameDbs(samples, frame)) if (db > loudest) loudest = db;
  return loudest < SILENT_DB;
}
