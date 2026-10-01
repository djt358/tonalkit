// Device rate -> 16 kHz: a Kaiser-windowed sinc low-pass evaluated at each output sample's
// fractional input position (exact rational polyphase table for the usual device rates).
//
// For the 16 kHz target the filter passes 0-6.4 kHz flat, is -6 dB at 7.2 kHz and stops
// (>= 70 dB down) from 8 kHz, the output's Nyquist frequency: nothing above 8 kHz folds back.

export const TARGET_RATE = 16000;
export const CUTOFF_HZ = 7200;
const STOPBAND_DB = 70;
const MAX_PHASES = 4096; // beyond this (odd rates) weights are computed per output sample

function gcd(a, b) {
  while (b) [a, b] = [b, a % b];
  return a;
}

function besselI0(x) {
  let sum = 1, term = 1;
  for (let k = 1; k < 64; k++) {
    term *= (x / (2 * k)) * (x / (2 * k));
    sum += term;
    if (term < sum * 1e-12) break;
  }
  return sum;
}

function design(inRate, outRate) {
  const g = gcd(inRate, outRate);
  const L = outRate / g; // output samples per ...
  const M = inRate / g; // ... this many input samples
  const nyquist = Math.min(inRate, outRate) / 2;
  const cutoff = Math.min(CUTOFF_HZ, 0.9 * nyquist); // -6 dB point
  const transition = 2 * (nyquist - cutoff); // full width; the stopband starts at the Nyquist
  const beta = 0.1102 * (STOPBAND_DB - 8.7);
  const halfSeconds = (STOPBAND_DB - 7.95) / (2 * 14.36 * transition);
  const K = Math.ceil(halfSeconds * inRate); // taps on each side, in input samples
  const fc = cutoff / inRate; // cycles per input sample
  const i0beta = besselI0(beta);
  const span = halfSeconds * inRate;

  // Normalised weights for an output instant `frac` input samples past input sample i;
  // weight j applies to input sample i - K + 1 + j.
  const weights = (frac) => {
    const w = new Float64Array(2 * K);
    let sum = 0;
    for (let j = 0; j < 2 * K; j++) {
      const d = j - K + 1 - frac;
      const x = d / span;
      if (Math.abs(x) >= 1) continue;
      const arg = 2 * Math.PI * fc * d;
      const sinc = d === 0 ? 1 : Math.sin(arg) / arg;
      w[j] = 2 * fc * sinc * (besselI0(beta * Math.sqrt(1 - x * x)) / i0beta);
      sum += w[j];
    }
    for (let j = 0; j < w.length; j++) w[j] /= sum; // unity DC gain at every phase
    return w;
  };
  const table = L <= MAX_PHASES ? Array.from({ length: L }, (_, p) => weights(p / L)) : null;
  return { L, M, K, phase: (p) => (table ? table[p] : weights(p / L)) };
}

/**
 * Resamples mono float samples from `inRate` to `outRate` (default 16 kHz).
 * @param {Float32Array} input
 * @param {number} inRate integer Hz
 * @param {number} [outRate]
 * @returns {Float32Array}
 */
export function resample(input, inRate, outRate = TARGET_RATE) {
  if (!Number.isInteger(inRate) || inRate <= 0 || !Number.isInteger(outRate) || outRate <= 0) {
    throw new RangeError(`resample: bad rates ${inRate} -> ${outRate}`);
  }
  if (inRate === outRate) return Float32Array.from(input);
  const { L, M, K, phase } = design(inRate, outRate);
  const n = input.length;
  const out = new Float32Array(Math.floor((n * L) / M));
  for (let o = 0; o < out.length; o++) {
    const pos = o * M;
    const i = Math.floor(pos / L);
    const w = phase(pos - i * L);
    const base = i - K + 1;
    const j0 = Math.max(0, -base);
    const j1 = Math.min(w.length, n - base);
    let acc = 0;
    for (let j = j0; j < j1; j++) acc += input[base + j] * w[j];
    out[o] = acc;
  }
  return out;
}
