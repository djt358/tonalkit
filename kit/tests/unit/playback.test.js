import { test } from "node:test";
import assert from "node:assert/strict";
import { encodeWav } from "../../app/wav.js";
import { Player, wavSamples } from "../../app/playback.js";

test("a kept take decodes back to its samples and rate", () => {
  const samples = Float32Array.from([0, 0.5, -0.5, 0.25]);
  const out = wavSamples(encodeWav(samples, 16000));
  assert.equal(out.rate, 16000);
  assert.deepEqual(Array.from(out.samples, (s) => Math.round(s * 4) / 4), [0, 0.5, -0.5, 0.25]);
});

test("the player starts a buffer source in the given context and stops it", () => {
  const calls = [];
  const source = { connect: () => calls.push("connect"), start: () => calls.push("start"), stop: () => calls.push("stop") };
  const ctx = {
    state: "suspended",
    destination: {},
    resume: () => (calls.push("resume"), Promise.resolve()),
    createBuffer: (ch, n, rate) => ({ ch, n, rate, copyToChannel: () => calls.push(`buffer ${n}@${rate}`) }),
    createBufferSource: () => source,
  };
  const player = new Player();
  player.play(ctx, encodeWav(new Float32Array(160), 16000));
  player.stop();
  assert.deepEqual(calls, ["resume", "buffer 160@16000", "connect", "start", "stop"]);
});
