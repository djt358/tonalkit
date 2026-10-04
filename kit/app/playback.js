// Plays a kept take (the kit's own 16-bit mono PCM WAV) through Web Audio, in the capture's
// AudioContext. On iOS an <audio> element can stay silent, or go to the earpiece, while the
// microphone is open; the capture's context is already running and plays at once.

/** The samples of a 16-bit mono PCM WAV as floats, and its rate. */
export function wavSamples(wav) {
  const bytes = wav instanceof Uint8Array ? wav : new Uint8Array(wav);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const rate = view.getUint32(24, true);
  let at = 12;
  while (at + 8 <= bytes.length) {
    const id = String.fromCharCode(...bytes.subarray(at, at + 4));
    const size = view.getUint32(at + 4, true);
    if (id === "data") {
      const n = Math.floor(Math.min(size, bytes.length - at - 8) / 2);
      const samples = new Float32Array(n);
      for (let i = 0; i < n; i++) samples[i] = view.getInt16(at + 8 + 2 * i, true) / 32768;
      return { samples, rate };
    }
    at += 8 + size + (size & 1);
  }
  throw new Error("not a PCM WAV: no data chunk");
}

export class Player {
  constructor() {
    this.source = null;
  }

  /** Plays `wav` in `ctx` from the start, stopping anything this player was playing. */
  play(ctx, wav) {
    this.stop();
    if (ctx.state === "suspended") ctx.resume().catch(() => {}); // called from a tap
    const { samples, rate } = wavSamples(wav);
    const buffer = ctx.createBuffer(1, Math.max(1, samples.length), rate);
    buffer.copyToChannel(samples, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => this.source === source && (this.source = null);
    source.start();
    this.source = source;
  }

  stop() {
    if (!this.source) return;
    try {
      this.source.stop();
    } catch {
      // already ended
    }
    this.source = null;
  }
}
