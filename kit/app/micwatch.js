// Runs the live microphone check (miccheck.js liveVerdict) while the mic screen is open: listens
// to the capture's level frames and reports a verdict every quarter second until stopped.

import { liveVerdict } from "./miccheck.js";

const TICK_MS = 250;

/**
 * @param {{onLevel: (fn: (db: number) => void) => () => void}} capture
 * @param {(result: ReturnType<typeof liveVerdict>) => void} onVerdict called with each verdict
 * @param {() => number} now milliseconds (tests pass a fake clock)
 * @returns {() => void} stop
 */
export function watchMic(capture, onVerdict, now = () => performance.now()) {
  const frames = [];
  const started = now();
  let heard = false;
  const off = capture.onLevel((db) => frames.push(db));
  const timer = setInterval(() => {
    const result = liveVerdict(frames, (now() - started) / 1000, heard);
    heard = result.heard;
    onVerdict(result);
  }, TICK_MS);
  return () => {
    clearInterval(timer);
    off();
  };
}
