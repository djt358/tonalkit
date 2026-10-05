import { test } from "node:test";
import assert from "node:assert/strict";
import { trim, MARGIN_S } from "../../app/trim.js";
import { sine, noise, concat } from "./support.js";

const RATE = 16000;
const FRAME = RATE / 100; // the trimmer's 10 ms frames
const silence = (s, seed = 3) => noise(RATE, s, -70, seed);
const vowel = (s, db = -20) => sine(220, RATE, s, Math.pow(10, db / 20) * Math.SQRT2);

test("leading and trailing silence go, 150 ms margins stay", () => {
  const take = concat(silence(0.6), vowel(0.5), silence(0.8, 4));
  const { samples, start, end, quiet } = trim(take, RATE);
  assert.equal(quiet, false);
  const speechStart = 0.6 * RATE, speechEnd = 1.1 * RATE;
  // Within one frame of the ideal cut on each side, and never inside the margin.
  assert.ok(start <= speechStart - MARGIN_S * RATE && start >= speechStart - MARGIN_S * RATE - FRAME, `start ${start}`);
  assert.ok(end >= speechEnd + MARGIN_S * RATE && end <= speechEnd + MARGIN_S * RATE + FRAME, `end ${end}`);
  assert.equal(samples.length, end - start);
  assert.deepEqual(samples, take.subarray(start, end));
});

test("a pause inside speech is never trimmed", () => {
  const take = concat(silence(0.4), vowel(0.3), silence(0.5, 5), vowel(0.3), silence(0.4, 6));
  const { samples, start, end } = trim(take, RATE);
  assert.ok(start <= 0.4 * RATE - MARGIN_S * RATE);
  assert.ok(end >= 1.5 * RATE + MARGIN_S * RATE);
  assert.deepEqual(samples, take.subarray(start, end));
});

test("speech touching the edges of the take is kept whole", () => {
  const take = concat(vowel(0.5), silence(0.5));
  const { start, end } = trim(take, RATE);
  assert.equal(start, 0);
  assert.ok(end >= 0.5 * RATE + MARGIN_S * RATE);
  const late = concat(silence(0.5), vowel(0.5));
  assert.equal(trim(late, RATE).end, late.length);
});

test("a soft fricative-like onset before the vowel is kept", () => {
  const fricative = noise(RATE, 0.2, -45, 9); // like the 'sh' of 水: quiet, noisy, before the vowel
  const take = concat(silence(0.5), fricative, vowel(0.4), silence(0.5, 7));
  const { start } = trim(take, RATE);
  assert.ok(start <= 0.5 * RATE - MARGIN_S * RATE, `start ${start} cuts into the onset`);
});

test("a take that never rises above the noise is kept whole and flagged quiet", () => {
  const take = silence(1.5);
  const result = trim(take, RATE);
  assert.equal(result.quiet, true);
  assert.equal(result.start, 0);
  assert.equal(result.end, take.length);
  assert.deepEqual(result.samples, take);
});

test("very soft speech (below -50 dBFS) is kept whole and flagged quiet", () => {
  const take = concat(silence(0.5), vowel(0.5, -55), silence(0.5));
  const result = trim(take, RATE);
  assert.equal(result.quiet, true);
  assert.equal(result.samples.length, take.length);
});

test("a take that is speech almost throughout is kept whole but not flagged quiet", () => {
  const take = concat(silence(0.05), vowel(1.5), silence(0.05, 8));
  const result = trim(take, RATE);
  assert.equal(result.quiet, false);
  assert.equal(result.samples.length, take.length);
});

test("digital silence around speech is handled (no -Infinity arithmetic)", () => {
  const take = concat(new Float32Array(8000), vowel(0.5), new Float32Array(8000));
  const { start, end, quiet } = trim(take, RATE);
  assert.equal(quiet, false);
  assert.ok(start > 0 && end < take.length);
});

test("works at device rates too", () => {
  const rate = 48000;
  const take = concat(noise(rate, 0.5, -70), sine(220, rate, 0.5, 0.1), noise(rate, 0.5, -70, 2));
  const { start, end } = trim(take, rate);
  assert.ok(start <= 0.35 * rate && start >= 0.34 * rate - rate / 100);
  assert.ok(end >= 1.15 * rate && end <= 1.16 * rate + rate / 100);
});
