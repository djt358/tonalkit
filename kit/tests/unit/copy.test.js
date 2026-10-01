import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { COPY_KEYS, lookup, makeT, optionKey, loadCopy } from "../../app/copy.js";
import { SPEAKER_OPTIONS } from "../../app/session.js";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");

// Every dotted key of a copy object, flat or nested.
function keysOf(obj, prefix = "") {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === "object" ? keysOf(v, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

test("the stand-in copy has exactly the shared keys, all strings", () => {
  const standin = JSON.parse(read("../../app/standin/copy.json"));
  assert.deepEqual(keysOf(standin).sort(), [...COPY_KEYS].sort());
  for (const v of Object.values(standin)) assert.equal(typeof v, "string");
});

test("kit/copy.json (P1), when present, has exactly the shared keys", { skip: !existsSync(new URL("../../copy.json", import.meta.url)) && "kit/copy.json not merged yet" }, () => {
  const real = JSON.parse(read("../../copy.json"));
  assert.deepEqual(keysOf(real).sort(), [...COPY_KEYS].sort());
});

test("kit/CONSENT.md (P2), when present, starts with the version marker", { skip: !existsSync(new URL("../../CONSENT.md", import.meta.url)) && "kit/CONSENT.md not merged yet" }, () => {
  assert.match(read("../../CONSENT.md").split("\n")[0], /^<!-- consent: v\d+ -->$/);
});

test("every background answer has a copy key", () => {
  for (const [question, values] of Object.entries(SPEAKER_OPTIONS)) {
    assert.ok(COPY_KEYS.includes(`background.${question}.label`));
    for (const v of values) assert.ok(COPY_KEYS.includes(optionKey(question, v)), optionKey(question, v));
  }
  assert.equal(optionKey("reading", "hanzi+pinyin"), "background.reading.hanzi_pinyin");
});

test("lookup reads flat and nested copy; t() fills placeholders and falls back per key", () => {
  assert.equal(lookup({ "card.next": "Next" }, "card.next"), "Next");
  assert.equal(lookup({ card: { next: "Next" } }, "card.next"), "Next");
  assert.equal(lookup({ card: {} }, "card.next"), undefined);
  const t = makeT({ "card.progress": "{n} of {total}" }, { "card.next": "Weiter" });
  assert.equal(t("card.progress", { n: 3, total: 70 }), "3 of 70");
  assert.equal(t("card.next"), "Weiter");
  assert.equal(t("card.unknown"), "card.unknown");
  assert.equal(t("card.progress"), "{n} of {total}");
});

test("loadCopy prefers the deployed files and says when it fell back to stand-ins", async () => {
  const files = {
    "../copy.json": JSON.stringify({ "welcome.title": "Real title" }),
    "standin/copy.json": read("../../app/standin/copy.json"),
    "standin/CONSENT.md": read("../../app/standin/CONSENT.md"),
  };
  const fetcher = (withConsent) => async (url) => {
    const body = url === "../CONSENT.md" && withConsent ? "<!-- consent: v1 -->\n# Real" : files[url];
    return body === undefined ? { ok: false, status: 404 } : { ok: true, json: async () => JSON.parse(body), text: async () => body };
  };
  const real = await loadCopy(fetcher(true));
  assert.equal(real.t("welcome.title"), "Real title");
  assert.equal(real.t("welcome.start"), "Start", "missing key falls back to the stand-in");
  assert.equal(real.consentVersion, "v1");
  assert.equal(real.consentIsStandin, false);
  assert.equal(real.consentHtml, "<h2>Real</h2>");
  const standin = await loadCopy(fetcher(false));
  assert.equal(standin.consentIsStandin, true);
  assert.equal(standin.consentVersion, "standin");
});
