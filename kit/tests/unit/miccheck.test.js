import { test } from "node:test";
import assert from "node:assert/strict";
import { micVerdict, percentile, MIC_CHECK_S, NOISY_FLOOR_DB, LOW_SPEECH_DB, WARMUP_FRAMES } from "../../app/miccheck.js";

// 3 s of 50 ms level frames (dBFS RMS): `speech` of them at the speech level, the rest at the
// room's level, in a deterministic interleaving (talking in bursts, with pauses between words).
const FRAMES = Math.round(MIC_CHECK_S / 0.05);
function trace(roomDb, speechDb, speechFraction = 0.5) {
  const out = [];
  let acc = 0;
  for (let i = 0; i < FRAMES; i++) {
    acc += speechFraction;
    const talking = acc >= 1;
    if (talking) acc -= 1;
    // A little frame-to-frame wobble so percentiles aren't read off a constant.
    out.push((talking ? speechDb : roomDb) + ((i * 7) % 5) - 2);
  }
  return out;
}

test("the check listens for about three seconds; thresholds as the brief sets them", () => {
  assert.ok(MIC_CHECK_S >= 2.5 && MIC_CHECK_S <= 3.5);
  assert.equal(NOISY_FLOOR_DB, -45);
  assert.equal(LOW_SPEECH_DB, -40);
});

test("percentile: nearest-rank on a sorted copy, input untouched", () => {
  const xs = [5, 1, 4, 2, 3];
  assert.equal(percentile(xs, 0.1), 1);
  assert.equal(percentile(xs, 0.5), 3);
  assert.equal(percentile(xs, 0.9), 5);
  assert.deepEqual(xs, [5, 1, 4, 2, 3]);
  assert.equal(percentile([], 0.5), -Infinity);
});

test("a quiet room and a normal voice: ok", () => {
  const v = micVerdict(trace(-62, -24));
  assert.equal(v.verdict, "ok");
  assert.ok(v.floor < -55 && v.speech > -30, JSON.stringify(v));
});

test("a noisy room (cafe, TV): noisy, even while the person talks", () => {
  assert.equal(micVerdict(trace(-38, -22)).verdict, "noisy");
  assert.equal(micVerdict(trace(-42, -20, 0.7)).verdict, "noisy");
});

test("a whisper, or a covered microphone: low", () => {
  assert.equal(micVerdict(trace(-62, -48)).verdict, "low");
  assert.equal(micVerdict(trace(-95, -95)).verdict, "low");
});

test("someone who says nothing in a quiet room hears low (the copy asks them to speak up)", () => {
  assert.equal(micVerdict(trace(-60, -60, 0)).verdict, "low");
});

test("a short burst of speech (a fifth of the time) still counts as speech", () => {
  assert.equal(micVerdict(trace(-60, -25, 0.2)).verdict, "ok");
});

test("no level frames at all (audio never flowed): low", () => {
  assert.equal(micVerdict([]).verdict, "low");
});

// iOS can hand over digital silence for the first frames while the microphone warms up.
const warmUp = (frames) => [...Array(WARMUP_FRAMES).fill(-120), ...frames];

test("M1: leading digital silence does not hide a noisy room (a short check, where it would set the floor)", () => {
  assert.equal(WARMUP_FRAMES, 4);
  const noisy = trace(-38, -22).slice(0, 36); // 36 real frames + 4 zeros: the zeros are 10% of them
  assert.equal(micVerdict(noisy).verdict, "noisy");
  const read = micVerdict(warmUp(noisy));
  assert.equal(read.verdict, "noisy");
  assert.ok(read.floor > NOISY_FLOOR_DB, JSON.stringify(read));
  assert.equal(micVerdict(warmUp(trace(-38, -22))).verdict, "noisy", "and in a full three-second check");
});

test("M1: leading digital silence does not change a good or a quiet reading either", () => {
  assert.equal(micVerdict(warmUp(trace(-62, -24))).verdict, "ok");
  assert.equal(micVerdict(warmUp(trace(-62, -48))).verdict, "low");
});

test("M1: with too few frames to spare, every frame counts (a mic that only ever sent silence is low)", () => {
  assert.equal(micVerdict(Array(WARMUP_FRAMES + 5).fill(-120)).verdict, "low");
  assert.equal(micVerdict(Array(10).fill(-30)).verdict, "noisy");
});
