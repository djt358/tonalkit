// Shared helpers for the kit's unit tests: synthetic signals and their measurements.
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export function sine(freq, rate, seconds, amp = 0.5) {
  const n = Math.round(rate * seconds);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = amp * Math.sin((2 * Math.PI * freq * i) / rate);
  return out;
}

// Deterministic white noise at a given RMS (dBFS), so tests never depend on Math.random.
export function noise(rate, seconds, db, seed = 1) {
  const n = Math.round(rate * seconds);
  const out = new Float32Array(n);
  let s = seed >>> 0;
  const amp = Math.pow(10, db / 20) * Math.sqrt(3); // uniform [-a, a] has RMS a/sqrt(3)
  for (let i = 0; i < n; i++) {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    out[i] = amp * ((s / 4294967296) * 2 - 1);
  }
  return out;
}

export function concat(...parts) {
  const out = new Float32Array(parts.reduce((a, p) => a + p.length, 0));
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

export function add(a, b) {
  const out = new Float32Array(Math.max(a.length, b.length));
  for (let i = 0; i < out.length; i++) out[i] = (a[i] ?? 0) + (b[i] ?? 0);
  return out;
}

// The middle of a signal, away from the edge transients of any filter.
export function middle(x, fraction = 0.6) {
  const cut = Math.floor((x.length * (1 - fraction)) / 2);
  return x.subarray(cut, x.length - cut);
}

export function rmsOf(x) {
  let acc = 0;
  for (let i = 0; i < x.length; i++) acc += x[i] * x[i];
  return Math.sqrt(acc / x.length);
}

// Frequency from positive-going zero crossings (linearly interpolated): exact to well under 0.01 Hz
// for a clean sine over a few hundred cycles.
export function zeroCrossingFreq(x, rate) {
  const crossings = [];
  for (let i = 1; i < x.length; i++) {
    if (x[i - 1] < 0 && x[i] >= 0) crossings.push(i - 1 + -x[i - 1] / (x[i] - x[i - 1]));
  }
  return ((crossings.length - 1) * rate) / (crossings[crossings.length - 1] - crossings[0]);
}

// Least-squares fit of a*sin + b*cos + c at a known frequency; returns the residual's RMS.
export function residualRms(x, freq, rate) {
  const w = (2 * Math.PI * freq) / rate;
  let ss = 0, cc = 0, sc = 0, s1 = 0, c1 = 0, xs = 0, xc = 0, x1 = 0;
  const n = x.length;
  for (let i = 0; i < n; i++) {
    const s = Math.sin(w * i), c = Math.cos(w * i);
    ss += s * s; cc += c * c; sc += s * c; s1 += s; c1 += c;
    xs += x[i] * s; xc += x[i] * c; x1 += x[i];
  }
  // Solve the 3x3 normal equations by Cramer's rule.
  const A = [[ss, sc, s1], [sc, cc, c1], [s1, c1, n]];
  const B = [xs, xc, x1];
  const det = (m) =>
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
    m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
    m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  const d = det(A);
  const sol = [0, 1, 2].map((k) => det(A.map((row, r) => row.map((v, c) => (c === k ? B[r] : v)))) / d);
  let acc = 0;
  for (let i = 0; i < n; i++) {
    const e = x[i] - (sol[0] * Math.sin(w * i) + sol[1] * Math.cos(w * i) + sol[2]);
    acc += e * e;
  }
  return Math.sqrt(acc / n);
}

export const db = (ratio) => 20 * Math.log10(ratio);

// Runs a Python snippet with the given file path as argv[1]; returns stdout (throws on failure).
export function python(code, bytes, suffix = ".bin") {
  const dir = mkdtempSync(join(tmpdir(), "tonekit-kit-"));
  try {
    const path = join(dir, `file${suffix}`);
    writeFileSync(path, bytes);
    return execFileSync("python3", ["-c", code, path], { encoding: "utf8" });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
