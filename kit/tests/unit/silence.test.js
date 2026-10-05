import { test } from "node:test";
import assert from "node:assert/strict";
import { isSilentTake, SILENT_DB } from "../../app/silence.js";
import { frameDbs } from "../../app/level.js";
import { sine, noise, concat } from "./support.js";

const tone = (rate, seconds, frameDb) => sine(220, rate, seconds, Math.pow(10, frameDb / 20) * Math.SQRT2); // RMS = frameDb

test("the threshold is -55 dBFS on the loudest 50 ms", () => {
  assert.equal(SILENT_DB, -55);
});

test("a take of zeros (the microphone delivered nothing) is silent, at any rate", () => {
  for (const rate of [16000, 44100, 48000]) assert.equal(isSilentTake(new Float32Array(rate * 2), rate), true, `${rate}`);
});

test("a take of the room alone (no voice) is silent", () => {
  assert.equal(isSilentTake(noise(48000, 2, -70), 48000), true);
});

test("the line sits at -55 dBFS: just under is refused, just over is kept", () => {
  assert.equal(isSilentTake(tone(48000, 1, -56), 48000), true);
  assert.equal(isSilentTake(tone(48000, 1, -54), 48000), false);
});

test("a quiet speaker's take is kept: vowels near -43 dB are 12 dB over the line", () => {
  const room = noise(48000, 0.5, -62);
  assert.equal(isSilentTake(concat(room, tone(48000, 0.4, -43), room), 48000), false);
});

test("one loud-enough word anywhere in a long, otherwise silent take keeps it", () => {
  const quiet = noise(44100, 1.5, -80);
  assert.equal(isSilentTake(concat(quiet, tone(44100, 0.2, -40), quiet), 44100), false);
  assert.equal(isSilentTake(concat(tone(44100, 0.2, -40), quiet), 44100), false);
  assert.equal(isSilentTake(concat(quiet, tone(44100, 0.2, -40)), 44100), false);
});

test("a single stray sample in a take of zeros does not make it a take", () => {
  const take = new Float32Array(48000);
  take[20000] = 0.002; // -54 dBFS peak, but 50 ms of it is far lower
  assert.equal(isSilentTake(take, 48000), true);
});

test("a take shorter than one 50 ms frame, or an empty one, is refused", () => {
  assert.equal(isSilentTake(tone(48000, 0.04, -20), 48000), true);
  assert.equal(isSilentTake(new Float32Array(0), 48000), true);
});

test("frameDbs: dBFS RMS per whole frame, a partial last frame left out", () => {
  const x = concat(tone(1000, 0.2, -20), new Float32Array(150)); // 200 samples at -20, then 150 zeros
  const dbs = frameDbs(x, 100);
  assert.equal(dbs.length, 3);
  assert.ok(Math.abs(dbs[0] - -20) < 0.1 && Math.abs(dbs[1] - -20) < 0.1, `${dbs}`);
  assert.equal(dbs[2], -120);
  assert.equal(frameDbs(new Float32Array(99), 100).length, 0);
});
