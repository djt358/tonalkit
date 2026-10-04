import { test } from "node:test";
import assert from "node:assert/strict";
import { liveVerdict, SPEECH_WAIT_S, WINDOW_FRAMES } from "../../app/miccheck.js";

const QUIET = -60; // a quiet room
const VOICE = -25; // a normal voice
const WHISPER = -48;
const frames = (n, db) => Array.from({ length: n }, () => db);
const speaking = (n, voice) => Array.from({ length: n }, (_, i) => (i % 3 ? voice : QUIET)); // words and gaps

test("nothing is said until a second of frames has arrived", () => {
  assert.equal(liveVerdict(frames(10, VOICE), 0.5).verdict, "checking");
});

test("a voice is heard as soon as it is loud enough", () => {
  assert.equal(liveVerdict([...frames(10, QUIET), ...speaking(20, VOICE)], 1.5).verdict, "ok");
});

test("a quiet room with no voice yet keeps checking, and says quiet only after the wait", () => {
  assert.equal(liveVerdict(frames(40, QUIET), SPEECH_WAIT_S - 1).verdict, "checking");
  assert.equal(liveVerdict(frames(40, QUIET), SPEECH_WAIT_S).verdict, "low");
});

test("speaking up after 'a bit quiet' turns it into 'that sounds good' (the reported bug)", () => {
  const whisper = speaking(120, WHISPER);
  const first = liveVerdict(whisper, SPEECH_WAIT_S + 1);
  assert.equal(first.verdict, "low");
  const louder = liveVerdict([...whisper, ...speaking(20, VOICE)], SPEECH_WAIT_S + 2, first.heard);
  assert.equal(louder.verdict, "ok");
});

test("once a voice was heard, a pause doesn't bring 'quiet' back", () => {
  const heard = liveVerdict(speaking(30, VOICE), 2).heard;
  assert.equal(liveVerdict([...speaking(30, VOICE), ...frames(WINDOW_FRAMES, QUIET)], 9, heard).verdict, "ok");
});

test("a noisy room is noisy, voice or not", () => {
  assert.equal(liveVerdict(speaking(40, -20).map((d) => Math.max(d, -35)), 2).verdict, "noisy");
  assert.equal(liveVerdict(frames(40, -38), SPEECH_WAIT_S).verdict, "noisy");
});

test("silent warm-up frames don't count", () => {
  assert.equal(liveVerdict([...frames(4, -120), ...speaking(30, VOICE)], 2).verdict, "ok");
});
