// Microphone capture for the whole session: one getUserMedia stream with the browser's voice
// processing off, an AudioContext at the device rate, and the capture worklet. Takes are
// press-to-start / press-to-stop with 0.3 s of pre-roll and post-roll, so a word started a hair
// early or finished a hair late is never cut (the trimmer removes the extra silence).
import { toDb } from "./level.js";

export const CONSTRAINTS = Object.freeze({
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: false,
  channelCount: 1,
});
// What session.json's device.constraints records: these settings as the browser reports them,
// null where it doesn't (iOS Safari reports echoCancellation only; R83). deviceId, groupId and
// labels are never recorded.
const REPORTED = ["echoCancellation", "noiseSuppression", "autoGainControl"];

/** @param {MediaTrackSettings|undefined} settings @returns {Record<string, boolean|null>} */
export function reportedConstraints(settings) {
  return Object.fromEntries(REPORTED.map((k) => [k, typeof settings?.[k] === "boolean" ? settings[k] : null]));
}
export const PRE_ROLL_S = 0.3;
export const POST_ROLL_S = 0.3;
const LEVEL_S = 0.05;
// iOS can leave ctx.resume() pending for good after a call or Siri: wait this long, then rebuild.
const RESUME_TIMEOUT_MS = 3000;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export class MicError extends Error {
  /** @param {"blocked"|"unsupported"|"generic"} kind */
  constructor(kind, cause) {
    super(`microphone: ${kind}${cause?.name ? ` (${cause.name})` : ""}`);
    this.kind = kind;
    this.cause = cause;
  }
}

export function captureSupported() {
  return Boolean(
    globalThis.navigator?.mediaDevices?.getUserMedia &&
      (globalThis.AudioContext || globalThis.webkitAudioContext) &&
      globalThis.AudioWorkletNode &&
      globalThis.isSecureContext,
  );
}

async function getStream() {
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: { ...CONSTRAINTS }, video: false });
  } catch (e) {
    const kind = ["NotAllowedError", "SecurityError", "PermissionDeniedError"].includes(e?.name)
      ? "blocked"
      : e?.name === "TypeError"
        ? "unsupported"
        : "generic";
    throw new MicError(kind, e);
  }
}

export class Capture {
  constructor() {
    this.ctx = null;
    this.stream = null;
    this.source = null;
    this.node = null;
    this.levelListeners = new Set();
    this.onInterrupt = () => {};
    this.take = null; // {id, chunks, ended: Promise}
    this.nextId = 1;
    this.resumeTimeoutMs = RESUME_TIMEOUT_MS;
  }

  get rate() {
    return this.ctx.sampleRate;
  }

  get track() {
    return this.stream?.getAudioTracks()[0] ?? null;
  }

  /** session.device: the rate takes are captured at and the settings the browser applied. */
  get device() {
    const constraints = reportedConstraints(this.track?.getSettings?.());
    return { user_agent: navigator.userAgent, input_sample_rate: this.rate, constraints };
  }

  get live() {
    return Boolean(this.ctx && this.ctx.state === "running" && this.track?.readyState === "live" && !this.track.muted);
  }

  /** Call first thing in a tap handler: iOS only starts audio inside a user gesture. */
  resume() {
    return this.ctx && this.ctx.state !== "closed" ? this.ctx.resume().catch(() => {}) : Promise.resolve();
  }

  /**
   * Opens (or re-opens after an interruption) the microphone; rejects with MicError. Call it
   * synchronously from a tap handler: the AudioContext is created and resumed before the first
   * await, while iOS still counts the tap as a user gesture.
   */
  open() {
    if (!this.ctx || this.ctx.state === "closed") this.createContext();
    const resumed = this.resume();
    return this.finishOpen(resumed);
  }

  async finishOpen(resumed) {
    // A track iOS left muted after an interruption is live but silent: get a fresh one.
    if (this.track?.readyState !== "live" || this.track.muted) await this.attachStream();
    if (!this.node) await this.createGraph();
    else if (!this.source) this.connectSource();
    if (await this.started(resumed)) return;
    // The context is stuck (suspended or "interrupted" with resume() never settling): rebuild it
    // around the same microphone stream.
    this.rebuildContext();
    await this.createGraph();
    if (!(await this.started(this.resume()))) {
      throw new MicError("generic", new Error(`audio ${this.ctx.state}`));
    }
  }

  /** Whether the context runs after `resuming` and one more resume, each given resumeTimeoutMs. */
  async started(resuming) {
    for (const attempt of [resuming, null]) {
      if (this.ctx.state === "running") return true;
      await Promise.race([attempt ?? this.resume(), delay(this.resumeTimeoutMs)]);
    }
    return this.ctx.state === "running";
  }

  rebuildContext() {
    const stuck = this.ctx;
    this.createContext();
    stuck?.close().catch(() => {});
  }

  async attachStream() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.source?.disconnect();
    this.source = null;
    this.stream = await getStream();
    const track = this.track;
    const interrupted = () => this.interrupt();
    track.addEventListener("ended", interrupted);
    track.addEventListener("mute", interrupted);
  }

  createContext() {
    const Ctx = globalThis.AudioContext || globalThis.webkitAudioContext;
    this.ctx = new Ctx({ latencyHint: "interactive" });
    this.node = null;
    this.source = null;
    const ctx = this.ctx;
    ctx.addEventListener("statechange", () => {
      if (ctx === this.ctx && ctx.state !== "running") this.interrupt();
    });
  }

  async createGraph() {
    await this.ctx.audioWorklet.addModule(new URL("./capture-worklet.js", import.meta.url));
    this.node = new AudioWorkletNode(this.ctx, "tonekit-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: {
        preRollFrames: Math.round(PRE_ROLL_S * this.ctx.sampleRate),
        levelFrames: Math.round(LEVEL_S * this.ctx.sampleRate),
      },
    });
    this.node.port.onmessage = ({ data }) => this.message(data);
    // The worklet's output is silent; routing it to the destination keeps it pulled everywhere.
    const mute = new GainNode(this.ctx, { gain: 0 });
    this.node.connect(mute).connect(this.ctx.destination);
    this.connectSource();
  }

  connectSource() {
    this.source?.disconnect();
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.source.connect(this.node);
  }

  message(data) {
    if (data.type === "level") {
      for (const listener of this.levelListeners) listener(toDb(data.rms), data.peak);
    } else if (data.type === "chunk" && this.take?.id === data.id) {
      this.take.chunks.push(data.data);
    } else if (data.type === "end" && this.take?.id === data.id) {
      this.take.resolveEnd();
    }
  }

  interrupt() {
    if (this.take) this.abort();
    this.onInterrupt();
  }

  /** @param {(db: number, peak: number) => void} listener @returns {() => void} unsubscribe */
  onLevel(listener) {
    this.levelListeners.add(listener);
    return () => this.levelListeners.delete(listener);
  }

  /** The level frames (dBFS RMS, one per 50 ms) over the next `seconds`. */
  levels(seconds) {
    return new Promise((resolve) => {
      const frames = [];
      const off = this.onLevel((db) => frames.push(db));
      setTimeout(() => {
        off();
        resolve(frames);
      }, seconds * 1000);
    });
  }

  get recording() {
    return Boolean(this.take);
  }

  start() {
    if (this.take) this.abort();
    const id = this.nextId++;
    let resolveEnd;
    const ended = new Promise((r) => (resolveEnd = r));
    this.take = { id, chunks: [], ended, resolveEnd };
    this.node.port.postMessage({ type: "start", id });
  }

  /** Ends the take after the post-roll; resolves with its samples at `rate`. */
  async stop() {
    const take = this.take;
    if (!take) return new Float32Array(0);
    this.node.port.postMessage({ type: "stop", id: take.id, postRollFrames: Math.round(POST_ROLL_S * this.rate) });
    // If the audio stops flowing (an interruption), don't wait forever for the post-roll.
    const timeout = new Promise((r) => setTimeout(r, (POST_ROLL_S + 1.5) * 1000));
    await Promise.race([take.ended, timeout]);
    if (this.take === take) this.take = null;
    const out = new Float32Array(take.chunks.reduce((a, c) => a + c.length, 0));
    let at = 0;
    for (const c of take.chunks) {
      out.set(c, at);
      at += c.length;
    }
    return out;
  }

  /** Throws the current take away. */
  abort() {
    if (!this.take) return;
    this.node?.port.postMessage({ type: "abort", id: this.take.id });
    this.take.resolveEnd();
    this.take.chunks = [];
    this.take = null;
  }

  /** Releases the microphone (iOS's recording indicator goes off). */
  close() {
    this.abort();
    this.stream?.getTracks().forEach((t) => t.stop());
    const ctx = this.ctx;
    this.ctx = null;
    this.node = null;
    this.source = null;
    this.stream = null;
    ctx?.close().catch(() => {});
  }
}
