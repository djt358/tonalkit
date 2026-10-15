// AudioWorklet side of the capture: mixes the microphone to mono, reports levels, keeps a short
// pre-roll while idle, and between "start" and "stop" (+ post-roll) streams the take's samples to
// the main thread in batches. Sample-accurate: nothing between start and the end of the
// post-roll is dropped.

const BATCH = 4096;

class CaptureProcessor extends AudioWorkletProcessor {
  constructor({ processorOptions }) {
    super();
    this.ring = new Float32Array(Math.max(1, processorOptions.preRollFrames));
    this.ringAt = 0;
    this.ringFull = false;
    this.take = null; // {id, remaining}: remaining frames of post-roll, Infinity while recording
    this.batch = new Float32Array(BATCH);
    this.batchLen = 0;
    this.levelFrames = processorOptions.levelFrames;
    this.levelSum = 0;
    this.levelPeak = 0;
    this.levelCount = 0;
    this.port.onmessage = ({ data }) => this.command(data);
  }

  command(msg) {
    if (msg.type === "start") {
      this.take = { id: msg.id, remaining: Infinity };
      this.batchLen = 0;
      this.sendPreRoll();
    } else if (msg.type === "stop" && this.take?.id === msg.id) {
      this.take.remaining = Math.max(0, msg.postRollFrames);
      if (this.take.remaining === 0) this.finish();
    } else if (msg.type === "abort" && this.take?.id === msg.id) {
      this.take = null;
      this.batchLen = 0;
    }
  }

  sendPreRoll() {
    const n = this.ringFull ? this.ring.length : this.ringAt;
    const out = new Float32Array(n);
    if (this.ringFull) {
      out.set(this.ring.subarray(this.ringAt));
      out.set(this.ring.subarray(0, this.ringAt), this.ring.length - this.ringAt);
    } else {
      out.set(this.ring.subarray(0, this.ringAt));
    }
    this.ringAt = 0;
    this.ringFull = false;
    if (n) this.port.postMessage({ type: "chunk", id: this.take.id, data: out }, [out.buffer]);
  }

  remember(mono) {
    for (let i = 0; i < mono.length; i++) {
      this.ring[this.ringAt++] = mono[i];
      if (this.ringAt === this.ring.length) {
        this.ringAt = 0;
        this.ringFull = true;
      }
    }
  }

  record(mono) {
    let n = mono.length;
    if (this.take.remaining !== Infinity) {
      n = Math.min(n, this.take.remaining);
      this.take.remaining -= n;
    }
    for (let i = 0; i < n; i++) {
      this.batch[this.batchLen++] = mono[i];
      if (this.batchLen === BATCH) this.sendBatch();
    }
    if (this.take.remaining === 0) this.finish();
  }

  sendBatch() {
    if (!this.batchLen) return;
    const data = this.batch.slice(0, this.batchLen);
    this.port.postMessage({ type: "chunk", id: this.take.id, data }, [data.buffer]);
    this.batchLen = 0;
  }

  finish() {
    this.sendBatch();
    this.port.postMessage({ type: "end", id: this.take.id });
    this.take = null;
  }

  meter(mono) {
    for (let i = 0; i < mono.length; i++) {
      const v = mono[i];
      this.levelSum += v * v;
      const a = v < 0 ? -v : v;
      if (a > this.levelPeak) this.levelPeak = a;
    }
    this.levelCount += mono.length;
    if (this.levelCount >= this.levelFrames) {
      this.port.postMessage({ type: "level", rms: Math.sqrt(this.levelSum / this.levelCount), peak: this.levelPeak });
      this.levelSum = 0;
      this.levelPeak = 0;
      this.levelCount = 0;
    }
  }

  process(inputs) {
    const channels = inputs[0] ?? [];
    const frames = channels[0]?.length ?? 128;
    let mono;
    if (channels.length === 1) {
      mono = channels[0];
    } else {
      // No input (an interrupted source reads as silence) or several channels (mixed down).
      mono = new Float32Array(frames);
      for (const ch of channels) for (let i = 0; i < frames; i++) mono[i] += ch[i] / channels.length;
    }
    this.meter(mono);
    if (this.take) this.record(mono);
    else this.remember(mono);
    return true;
  }
}

registerProcessor("tonekit-capture", CaptureProcessor);
