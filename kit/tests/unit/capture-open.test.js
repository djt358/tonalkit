// Capture.open() against fake WebAudio/getUserMedia objects: the iOS failure modes a headless
// browser can't produce (a context whose resume() never settles, a live-but-muted track).
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { Capture, MicError } from "../../app/capture.js";

let contexts, streams, stuck;

class FakeContext {
  constructor() {
    this.state = "suspended";
    this.sampleRate = 48000;
    this.audioWorklet = { addModule: async () => {} };
    this.destination = {};
    this.stuck = stuck; // resume() never settles and the state never changes
    contexts.push(this);
  }
  addEventListener() {}
  resume() {
    if (this.stuck) return new Promise(() => {});
    this.state = "running";
    return Promise.resolve();
  }
  createMediaStreamSource() {
    return { connect() {}, disconnect() {} };
  }
  close() {
    this.state = "closed";
    return Promise.resolve();
  }
}

function fakeStream() {
  const track = {
    readyState: "live",
    muted: false,
    stopped: false,
    addEventListener() {},
    stop() {
      this.stopped = true;
      this.readyState = "ended";
    },
    getSettings: () => ({ echoCancellation: false }),
  };
  const stream = { getAudioTracks: () => [track], getTracks: () => [track] };
  streams.push(stream);
  return stream;
}

globalThis.AudioContext = FakeContext;
globalThis.AudioWorkletNode = class {
  constructor() {
    this.port = { postMessage() {} };
  }
  connect(node) {
    return node;
  }
};
globalThis.GainNode = class {
  connect(node) {
    return node;
  }
};
Object.defineProperty(globalThis.navigator, "mediaDevices", {
  value: { getUserMedia: async () => fakeStream() },
  configurable: true,
});

beforeEach(() => {
  contexts = [];
  streams = [];
  stuck = false;
});

const capture = () => Object.assign(new Capture(), { resumeTimeoutMs: 20 });

test("a first open builds one context and one stream, and reports R83 constraints", async () => {
  const c = capture();
  await c.open();
  assert.equal(contexts.length, 1);
  assert.equal(streams.length, 1);
  assert.equal(c.ctx.state, "running");
  assert.deepEqual(c.device.constraints, { echoCancellation: false, noiseSuppression: null, autoGainControl: null });
});

test("a context whose resume() never settles (iOS after a call) is rebuilt after the timeout", async () => {
  const c = capture();
  await c.open();
  const first = c.ctx;
  first.state = "interrupted";
  first.stuck = true;
  await c.open();
  assert.equal(contexts.length, 2, "a new context");
  assert.notEqual(c.ctx, first);
  assert.equal(first.state, "closed", "the stuck one is closed");
  assert.equal(c.ctx.state, "running");
  assert.equal(streams.length, 1, "the live microphone stream is kept");
});

test("if the rebuilt context is stuck too, open() rejects with a MicError (the next tap retries)", async () => {
  stuck = true;
  const c = capture();
  await assert.rejects(c.open(), (e) => e instanceof MicError && e.kind === "generic");
  assert.equal(contexts.length, 2);
});

test("a live but muted track (iOS after an interruption) is replaced by a fresh one", async () => {
  const c = capture();
  await c.open();
  const old = c.track;
  old.muted = true;
  await c.open();
  assert.equal(streams.length, 2);
  assert.equal(old.stopped, true);
  assert.equal(c.track.muted, false);
});

test("levels() collects the level frames over the window", async () => {
  const c = capture();
  const pending = c.levels(0.05);
  c.message({ type: "level", rms: 0.1, peak: 0.2 });
  c.message({ type: "level", rms: 0.01, peak: 0.02 });
  const got = await pending;
  assert.equal(got.length, 2);
  assert.ok(Math.abs(got[0] + 20) < 1e-9 && Math.abs(got[1] + 40) < 1e-9);
});
