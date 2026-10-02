import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CODE_ALPHABET,
  newCode,
  isCode,
  isoUtc,
  consentVersion,
  SPEAKER_OPTIONS,
  DEFAULT_SPEAKER,
  createSession,
  defaultScript,
  sessionDevice,
  cardState,
  skipRemaining,
  hasKeptTake,
} from "../../app/session.js";
import { cardOrder } from "../../app/order.js";

test("the code alphabet has no 0/O/1/I and 32 distinct symbols", () => {
  assert.equal(CODE_ALPHABET, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789");
  assert.equal(new Set(CODE_ALPHABET).size, 32);
  for (const bad of "0O1I") assert.ok(!CODE_ALPHABET.includes(bad));
});

test("codes are six characters from the alphabet, from crypto.getRandomValues", () => {
  const seen = new Map();
  for (let i = 0; i < 5000; i++) {
    const code = newCode();
    assert.match(code, /^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}$/);
    assert.ok(isCode(code));
    for (const ch of code) seen.set(ch, (seen.get(ch) ?? 0) + 1);
  }
  // 30 000 symbols over 32 letters: each ~937; every letter is used and none dominates.
  assert.equal(seen.size, 32);
  for (const n of seen.values()) assert.ok(n > 750 && n < 1130, `count ${n}`);
});

test("byte values map to the alphabet without bias (256 is a multiple of 32)", () => {
  const all = Uint8Array.from({ length: 256 }, (_, i) => i);
  let at = 0;
  const counts = new Map();
  for (let k = 0; k < 256 / 6 - 1; k++) {
    const code = newCode((n) => all.slice(at, (at += n)));
    for (const ch of code) counts.set(ch, (counts.get(ch) ?? 0) + 1);
  }
  const values = [...counts.values()];
  assert.ok(Math.max(...values) - Math.min(...values) <= 1);
});

test("isCode rejects the wrong length and ambiguous letters", () => {
  for (const bad of ["K7Q2M", "K7Q2MDX", "K7Q2M0", "k7q2md", "K7Q2MI", ""]) assert.equal(isCode(bad), false, bad);
});

test("timestamps are UTC ISO 8601 to the second", () => {
  assert.equal(isoUtc(new Date(Date.UTC(2026, 9, 3, 18, 2, 11, 987))), "2026-10-03T18:02:11Z");
});

test("the consent version comes from CONSENT.md's first line", () => {
  assert.equal(consentVersion("<!-- consent: v1 -->\n# Consent"), "v1");
  assert.equal(consentVersion("<!--consent:v2-->\r\n# Consent"), "v2");
  assert.equal(consentVersion("# Consent without a marker"), null, "no marker: the app refuses outside dev mode");
  assert.equal(consentVersion("# Title\n<!-- consent: v9 -->"), null, "only the first line counts");
});

test("background answers are exactly the contract's enums, prefilled to prefer_not; script has no prefer_not", () => {
  assert.deepEqual(SPEAKER_OPTIONS, {
    background: ["native", "heritage", "learner", "prefer_not"],
    grew_up_hearing: ["mainland", "taiwan", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not"],
    script: ["simplified", "traditional"],
    reading: ["hanzi", "hanzi+pinyin"],
  });
  assert.deepEqual(DEFAULT_SPEAKER, {
    background: "prefer_not",
    grew_up_hearing: "prefer_not",
    script: "simplified",
    reading: "hanzi",
  });
});

test("R74: until the person picks a script, it follows where they grew up hearing Mandarin", () => {
  assert.equal(defaultScript("taiwan"), "traditional");
  assert.equal(defaultScript("hong_kong_macau"), "traditional");
  for (const other of ["mainland", "singapore_malaysia", "other", "prefer_not"]) assert.equal(defaultScript(other), "simplified");
});

test("the session keeps the first microphone's rate and settings; a later change is only reported", () => {
  const first = { user_agent: "UA", input_sample_rate: 48000, constraints: { echoCancellation: false, noiseSuppression: null, autoGainControl: null } };
  assert.deepEqual(sessionDevice(null, first), { device: first, change: null });
  assert.deepEqual(sessionDevice(first, structuredClone(first)), { device: first, change: null });
  const airpods = { ...first, input_sample_rate: 24000, constraints: { ...first.constraints, echoCancellation: true } };
  const { device, change } = sessionDevice(first, airpods);
  assert.equal(device, first);
  assert.match(change, /48000.*24000/);
  assert.match(change, /echoCancellation/);
});

test("a new session carries a fresh code, the deck it loaded, its card order and start time", () => {
  const deck = { id: "s05-v1", sha256: "ab".repeat(32), text: "{}" };
  const cards = [
    { id: "g01-c", set: "gate", pair: "g01" },
    { id: "g01-e", set: "gate", pair: "g01" },
    { id: "g02-c", set: "gate", pair: "g02" },
    { id: "g02-e", set: "gate", pair: "g02" },
  ];
  const now = new Date(Date.UTC(2026, 9, 3, 18, 2, 11));
  const s = createSession({ deck, cards, dev: false, now });
  assert.ok(isCode(s.code));
  assert.equal(s.started_at, "2026-10-03T18:02:11Z");
  assert.deepEqual(s.deck, deck);
  assert.deepEqual(s.order, cardOrder(cards, s.code));
  assert.equal(s.index, 0);
  assert.equal(s.finished_at, null);
  assert.equal(s.step, "consent");
  assert.deepEqual(s.speaker, DEFAULT_SPEAKER);
  assert.notEqual(s.speaker, DEFAULT_SPEAKER, "a copy, not the shared default");
});

test("finishing early: every card without a kept take counts as skipped; kept takes stay", () => {
  const s = createSession({ deck: { id: "d", sha256: "0".repeat(64), text: "{}" }, cards: ["a", "b", "c", "d"].map((id) => ({ id, set: "register" })), dev: false });
  assert.equal(hasKeptTake(s), false);
  Object.assign(cardState(s, "a"), { takes: 1, kept: true });
  cardState(s, "b").skipped = true;
  cardState(s, "c").takes = 1; // a take thrown away by an interruption: nothing kept
  assert.equal(hasKeptTake(s), true);
  skipRemaining(s);
  assert.deepEqual(
    Object.fromEntries(s.order.map((id) => [id, [s.cards[id].kept, s.cards[id].skipped]])),
    { a: [true, false], b: [false, true], c: [false, true], d: [false, true] },
  );
});
