import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionJson, buildBundle, bundleName, shareBundle, SCHEMA } from "../../app/export.js";
import { processTake } from "../../app/take.js";
import { python, sine, noise, concat } from "./support.js";

function finishedSession() {
  return {
    v: 1,
    code: "K7Q2MD",
    deck: { id: "s05-v1", sha256: "ab".repeat(32), text: "{...}" },
    dev: false,
    started_at: "2026-10-03T18:02:11Z",
    finished_at: "2026-10-03T18:24:40Z",
    consent: { version: "v1", agreed_at: "2026-10-03T18:02:30Z" },
    speaker: { background: "native", grew_up_hearing: "taiwan", script: "traditional", reading: "hanzi+pinyin" },
    script_chosen: true,
    device: {
      user_agent: "Mozilla/5.0 (iPhone)",
      input_sample_rate: 48000,
      constraints: { echoCancellation: false, noiseSuppression: null, autoGainControl: null },
    },
    order: ["g01-c", "r01", "g01-e", "r02"],
    index: 3,
    cards: {
      "g01-c": { takes: 2, kept: true, skipped: false, duration_s: 1.42, peak: 0.51, quiet: false },
      r01: { takes: 0, kept: false, skipped: true, duration_s: 0, peak: 0, quiet: false },
      "g01-e": { takes: 1, kept: true, skipped: false, duration_s: 1.2, peak: 0.4, quiet: true },
      r02: { takes: 1, kept: true, skipped: false, duration_s: 0.9, peak: 0.3, quiet: false },
    },
    step: "done",
  };
}

test("session.json has exactly the contract's fields, in reading order", () => {
  const json = sessionJson(finishedSession());
  assert.deepEqual(json, {
    schema: SCHEMA,
    deck: { id: "s05-v1", sha256: "ab".repeat(32) },
    session: "K7Q2MD",
    started_at: "2026-10-03T18:02:11Z",
    finished_at: "2026-10-03T18:24:40Z",
    consent: { version: "v1", agreed_at: "2026-10-03T18:02:30Z" },
    speaker: { background: "native", grew_up_hearing: "taiwan", reading: "hanzi+pinyin", script: "traditional" },
    device: {
      user_agent: "Mozilla/5.0 (iPhone)",
      input_sample_rate: 48000,
      constraints: { echoCancellation: false, noiseSuppression: null, autoGainControl: null },
    },
    clips: [
      { card: "g01-c", file: "clips/g01-c.wav", takes: 2, duration_s: 1.42, peak: 0.51 },
      { card: "g01-e", file: "clips/g01-e.wav", takes: 1, duration_s: 1.2, peak: 0.4 },
      { card: "r02", file: "clips/r02.wav", takes: 1, duration_s: 0.9, peak: 0.3 },
    ],
    skipped: ["r01"],
  });
  assert.equal(SCHEMA, "tonekit.session.v1");
});

test("the bundle is a zip of session.json and one WAV per kept clip, named for deck and code", async () => {
  const session = finishedSession();
  const take = concat(noise(48000, 0.4, -70), sine(220, 48000, 0.8, 0.3), noise(48000, 0.4, -70, 2));
  const wav = processTake(take, 48000).wav;
  const file = await buildBundle(session, async () => wav);
  assert.equal(bundleName(session), "tonekit-s05-v1-K7Q2MD.zip");
  assert.equal(file.name, "tonekit-s05-v1-K7Q2MD.zip");
  assert.equal(file.type, "application/zip");
  const out = python(
    [
      "import sys, zipfile, json, wave, io",
      "z = zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None",
      "s = json.loads(z.read('session.json'))",
      "w = [wave.open(io.BytesIO(z.read(c['file']))) for c in s['clips']]",
      "print(json.dumps({'names': z.namelist(), 'session': s,",
      "  'wav': [[x.getframerate(), x.getnchannels(), x.getsampwidth()] for x in w]}))",
    ].join("\n"),
    new Uint8Array(await file.arrayBuffer()),
    ".zip",
  );
  const got = JSON.parse(out);
  assert.deepEqual(got.names, ["session.json", "clips/g01-c.wav", "clips/g01-e.wav", "clips/r02.wav"]);
  assert.deepEqual(got.session, sessionJson(session));
  assert.deepEqual(got.wav, [[16000, 1, 2], [16000, 1, 2], [16000, 1, 2]]);
});

test("a take becomes a trimmed 16 kHz clip with its duration and peak", () => {
  const take = concat(noise(48000, 0.5, -70), sine(220, 48000, 0.8, 0.3), noise(48000, 0.6, -70, 2));
  const clip = processTake(take, 48000);
  assert.ok(Math.abs(clip.duration_s - (0.8 + 0.3)) < 0.03, `duration ${clip.duration_s}`);
  assert.ok(Math.abs(clip.peak - 0.3) < 0.01, `peak ${clip.peak}`);
  assert.equal(clip.quiet, false);
  assert.equal(clip.wav.length, 44 + 2 * Math.round(clip.duration_s * 16000));
});

test("share: the share sheet when it takes files; otherwise the caller falls back to a download", async () => {
  const file = { name: "x.zip" };
  const nav = (share, canShare = () => true) => ({ share, canShare });
  assert.equal(await shareBundle(file, nav(async () => {})), "shared");
  assert.equal(await shareBundle(file, nav(async () => { throw Object.assign(new Error(), { name: "AbortError" }); })), "cancelled");
  assert.equal(await shareBundle(file, nav(async () => { throw Object.assign(new Error(), { name: "NotAllowedError" }); })), "failed");
  assert.equal(await shareBundle(file, nav(async () => {}, () => false)), "unsupported");
  assert.equal(await shareBundle(file, {}), "unsupported");
});
