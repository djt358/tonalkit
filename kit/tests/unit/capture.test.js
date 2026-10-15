import { test } from "node:test";
import assert from "node:assert/strict";
import { reportedConstraints } from "../../app/capture.js";

const NULLS = { echoCancellation: null, noiseSuppression: null, autoGainControl: null };

test("R83: iOS Safari's settings (only echoCancellation reported) give all three keys, null where unreported", () => {
  // What track.getSettings() returns on an iPhone: no noiseSuppression, no autoGainControl.
  const safari = { deviceId: "abc", groupId: "def", echoCancellation: false, sampleRate: 48000, sampleSize: 16, volume: 1 };
  assert.deepEqual(reportedConstraints(safari), { echoCancellation: false, noiseSuppression: null, autoGainControl: null });
});

test("Chromium's full report is recorded as it is", () => {
  const chromium = { echoCancellation: false, noiseSuppression: true, autoGainControl: false, channelCount: 1, deviceId: "x" };
  assert.deepEqual(reportedConstraints(chromium), { echoCancellation: false, noiseSuppression: true, autoGainControl: false });
});

test("nothing reported, or a non-boolean value, is null; identifiers are never recorded", () => {
  assert.deepEqual(reportedConstraints({}), NULLS);
  assert.deepEqual(reportedConstraints(undefined), NULLS);
  assert.deepEqual(reportedConstraints({ echoCancellation: "remote-only", noiseSuppression: 1, autoGainControl: undefined }), NULLS);
  assert.deepEqual(Object.keys(reportedConstraints({ deviceId: "x", groupId: "y", label: "AirPods" })), Object.keys(NULLS));
});
