import { test } from "node:test";
import assert from "node:assert/strict";
import { resample, TARGET_RATE } from "../../app/resample.js";
import { sine, middle, rmsOf, zeroCrossingFreq, residualRms, db } from "./support.js";

const RATES = [48000, 44100];

for (const rate of RATES) {
  test(`1 kHz sine from ${rate} Hz keeps its frequency, level and purity at 16 kHz`, () => {
    const input = sine(1000, rate, 2.0, 0.5);
    const out = resample(input, rate);
    assert.equal(out.length, Math.floor((input.length * TARGET_RATE) / rate));
    const mid = middle(out);
    assert.ok(Math.abs(zeroCrossingFreq(mid, TARGET_RATE) - 1000) < 1, "frequency within 1 Hz");
    const ratio = rmsOf(mid) / rmsOf(middle(input));
    assert.ok(Math.abs(ratio - 1) < 0.01, `RMS within 1% (ratio ${ratio})`);
    // Anything that isn't the 1 kHz sine (aliases, images, ripple) sits below -40 dB.
    const spurious = db(residualRms(mid, 1000, TARGET_RATE) / rmsOf(mid));
    assert.ok(spurious < -40, `spurious energy ${spurious.toFixed(1)} dB`);
  });

  test(`content above 8 kHz at ${rate} Hz does not alias into the 16 kHz output`, () => {
    for (const freq of [8500, 9000, 10000, 12000, 15000, 20000]) {
      const input = sine(freq, rate, 1.0, 0.5);
      const out = resample(input, rate);
      const level = db(rmsOf(middle(out)) / rmsOf(middle(input)));
      assert.ok(level < -40, `${freq} Hz leaks at ${level.toFixed(1)} dB`);
    }
  });

  test(`the passband is flat at ${rate} Hz (5 kHz within 1%)`, () => {
    const input = sine(5000, rate, 1.0, 0.5);
    const mid = middle(resample(input, rate));
    assert.ok(Math.abs(zeroCrossingFreq(mid, TARGET_RATE) - 5000) < 1);
    const ratio = rmsOf(mid) / rmsOf(middle(input));
    assert.ok(Math.abs(ratio - 1) < 0.01, `ratio ${ratio}`);
  });
}

test("a frequency sweep through the passband keeps its level at every point", () => {
  for (const rate of RATES) {
    for (const freq of [80, 150, 300, 600, 2000, 4000, 6000]) {
      const input = sine(freq, rate, 1.0, 0.3);
      const ratio = rmsOf(middle(resample(input, rate))) / rmsOf(middle(input));
      assert.ok(Math.abs(ratio - 1) < 0.01, `${freq} Hz at ${rate}: ratio ${ratio}`);
    }
  }
});

test("16 kHz input passes through unchanged", () => {
  const input = sine(440, 16000, 0.5);
  assert.deepEqual(resample(input, 16000), input);
});

test("other device rates work too (upsampling from 8 kHz, downsampling from 96 kHz)", () => {
  for (const rate of [8000, 22050, 24000, 32000, 96000]) {
    const out = resample(sine(500, rate, 1.0), rate);
    assert.ok(Math.abs(zeroCrossingFreq(middle(out), TARGET_RATE) - 500) < 1, `rate ${rate}`);
  }
});

test("a DC level stays put (unity gain at every fractional phase)", () => {
  const input = new Float32Array(44100).fill(0.25);
  const mid = middle(resample(input, 44100));
  for (const v of mid) assert.ok(Math.abs(v - 0.25) < 1e-4);
});

test("rejects nonsense rates", () => {
  assert.throws(() => resample(new Float32Array(10), 0));
  assert.throws(() => resample(new Float32Array(10), 44100.5));
});
