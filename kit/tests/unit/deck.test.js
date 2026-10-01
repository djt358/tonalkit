import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { loadDeck, parseDeck, shownCards, deckFromStored, DeckError, sha256Hex } from "../../app/deck.js";

const STANDIN = new URL("../../app/standin/deck.json", import.meta.url);
const standinBytes = readFileSync(STANDIN);

// A fetch stand-in over a map of URL -> bytes (anything else is a 404).
const fakeFetch = (files) => async (url) => {
  const body = files[url];
  return body === undefined
    ? { ok: false, status: 404 }
    : { ok: true, status: 200, arrayBuffer: async () => Uint8Array.from(body).buffer };
};

const deckBytes = (cards, id = "s05-v1") =>
  Buffer.from(JSON.stringify({ deck: { id, lect: "cmn", version: 1, title: "t" }, card: cards }, null, 1) + "\n\n");
const card = (id, status = "approved", extra = {}) => ({ id, set: "register", text: "一", status, ...extra });

test("the stand-in deck parses and has a gate pair, an isolated and a phrase card", () => {
  const { meta, cards } = parseDeck(standinBytes.toString("utf8"));
  assert.equal(meta.id, "standin-v1");
  assert.deepEqual(cards.map((c) => c.id), ["g01-c", "g01-e", "r01", "r02"]);
  assert.ok(cards.some((c) => c.context === "isolated") && cards.some((c) => c.prompt_note));
});

test("the sha256 is over the exact bytes served (whitespace included)", async () => {
  const bytes = deckBytes([card("a1")]);
  const deck = await loadDeck({ id: "s05-v1", fetcher: fakeFetch({ "../deck/s05-v1.json": bytes }) });
  assert.equal(deck.sha256, createHash("sha256").update(bytes).digest("hex"));
  assert.equal(deck.text, bytes.toString("utf8"));
  assert.equal(deck.standin, false);
  assert.equal(await sha256Hex(new TextEncoder().encode("abc")),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("only approved cards are shown, unless in dev mode", async () => {
  const bytes = deckBytes([card("a1"), card("a2", "unverified"), card("a3")]);
  const fetcher = fakeFetch({ "../deck/s05-v1.json": bytes });
  assert.deepEqual((await loadDeck({ fetcher })).cards.map((c) => c.id), ["a1", "a3"]);
  assert.deepEqual((await loadDeck({ fetcher, dev: true })).cards.map((c) => c.id), ["a1", "a2", "a3"]);
  assert.deepEqual(shownCards([card("x", "unverified")], false), []);
});

test("a deck with no approved cards is refused outside dev mode", async () => {
  const fetcher = fakeFetch({ "../deck/s05-v1.json": deckBytes([card("a1", "unverified")]) });
  await assert.rejects(loadDeck({ fetcher }), DeckError);
});

test("a missing deck is an error, except in dev mode where the stand-in fills in", async () => {
  const fetcher = fakeFetch({ "standin/deck.json": standinBytes });
  await assert.rejects(loadDeck({ fetcher }), /HTTP 404/);
  const dev = await loadDeck({ fetcher, dev: true });
  assert.equal(dev.standin, true);
  assert.equal(dev.id, "standin-v1");
  assert.equal(dev.cards.length, 4);
});

test("?deck=standin picks the stand-in directly in dev mode only", async () => {
  const fetcher = fakeFetch({ "standin/deck.json": standinBytes, "../deck/s05-v1.json": deckBytes([card("a1")]) });
  assert.equal((await loadDeck({ id: "standin", dev: true, fetcher })).id, "standin-v1");
  await assert.rejects(loadDeck({ id: "standin", fetcher }), /HTTP 404/);
});

test("structural errors name the problem", () => {
  assert.throws(() => parseDeck("{"), /not JSON/);
  assert.throws(() => parseDeck('{"card": []}'), /deck.id/);
  assert.throws(() => parseDeck(deckBytes([card("Bad_Id")]).toString()), /bad card id Bad_Id/);
  assert.throws(() => parseDeck(deckBytes([card("a1"), card("a1")]).toString()), /duplicate card id a1/);
  assert.throws(() => parseDeck(deckBytes([{ id: "a1" }]).toString()), /a1 has no text/);
});

test("a stored deck is read back from its own text, not refetched", () => {
  const text = deckBytes([card("a1"), card("a2", "unverified")]).toString();
  const deck = deckFromStored({ id: "s05-v1", sha256: "f".repeat(64), text }, false);
  assert.equal(deck.sha256, "f".repeat(64));
  assert.deepEqual(deck.cards.map((c) => c.id), ["a1"]);
});
