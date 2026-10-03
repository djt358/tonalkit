import { test } from "node:test";
import assert from "node:assert/strict";
import { encodeWav } from "../../app/wav.js";
import { python } from "./support.js";

const ascii = (bytes, at, n) => String.fromCharCode(...bytes.subarray(at, at + n));

test("header: RIFF/WAVE, PCM, mono, 16 kHz, 16-bit, sizes", () => {
  const bytes = encodeWav(new Float32Array(1000), 16000);
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  assert.equal(bytes.length, 44 + 2000);
  assert.equal(ascii(bytes, 0, 4), "RIFF");
  assert.equal(v.getUint32(4, true), 36 + 2000);
  assert.equal(ascii(bytes, 8, 4), "WAVE");
  assert.equal(ascii(bytes, 12, 4), "fmt ");
  assert.equal(v.getUint32(16, true), 16);
  assert.equal(v.getUint16(20, true), 1, "PCM");
  assert.equal(v.getUint16(22, true), 1, "mono");
  assert.equal(v.getUint32(24, true), 16000);
  assert.equal(v.getUint32(28, true), 32000, "byte rate");
  assert.equal(v.getUint16(32, true), 2, "block align");
  assert.equal(v.getUint16(34, true), 16, "bits");
  assert.equal(ascii(bytes, 36, 4), "data");
  assert.equal(v.getUint32(40, true), 2000);
});

test("samples are scaled, rounded and clipped to +-1", () => {
  const bytes = encodeWav(Float32Array.from([0, 1, -1, 2, -2, 0.5, -0.5, 1e-6]), 16000);
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const got = Array.from({ length: 8 }, (_, i) => v.getInt16(44 + 2 * i, true));
  assert.deepEqual(got, [0, 32767, -32768, 32767, -32768, 16384, -16384, 0]);
});

test("Python's wave module reads it back", () => {
  const n = 16000;
  const samples = Float32Array.from({ length: n }, (_, i) => 0.5 * Math.sin((2 * Math.PI * 440 * i) / 16000));
  const out = python(
    "import sys, wave\nw = wave.open(sys.argv[1])\nprint(w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())",
    encodeWav(samples, 16000),
    ".wav",
  );
  assert.equal(out.trim(), `1 2 16000 ${n}`);
});
