// Signal level helpers shared by the trimmer, the take pipeline and the microphone check.

export const FLOOR_DB = -120; // what digital silence reads as

/** RMS of samples[start, end). */
export function rms(samples, start = 0, end = samples.length) {
  if (end <= start) return 0;
  let acc = 0;
  for (let i = start; i < end; i++) acc += samples[i] * samples[i];
  return Math.sqrt(acc / (end - start));
}

/** Linear amplitude -> dBFS, clamped at FLOOR_DB. */
export function toDb(amplitude) {
  return amplitude > 0 ? Math.max(FLOOR_DB, 20 * Math.log10(amplitude)) : FLOOR_DB;
}

/** dBFS RMS of each whole frame of `frame` samples (a partial last frame is left out). */
export function frameDbs(samples, frame) {
  const dbs = new Float64Array(Math.floor(samples.length / frame));
  for (let f = 0; f < dbs.length; f++) dbs[f] = toDb(rms(samples, f * frame, (f + 1) * frame));
  return dbs;
}

/** Largest absolute sample value. */
export function peakAbs(samples) {
  let peak = 0;
  for (let i = 0; i < samples.length; i++) {
    const a = Math.abs(samples[i]);
    if (a > peak) peak = a;
  }
  return peak;
}
