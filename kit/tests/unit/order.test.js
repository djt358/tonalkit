import { test } from "node:test";
import assert from "node:assert/strict";
import { cardOrder } from "../../app/order.js";
import { CODE_ALPHABET } from "../../app/session.js";

// Distinct codes from a fixed integer hash, so failures reproduce.
const codes = Array.from({ length: 400 }, (_, i) => {
  const x = Math.imul(i + 1, 2654435761) >>> 0;
  return Array.from({ length: 6 }, (_, k) => CODE_ALPHABET[(x >>> (5 * k)) & 31]).join("");
});

const pairCards = (prefix, n, set = "gate") =>
  Array.from({ length: n }, (_, i) => {
    const pair = `${prefix}${String(i + 1).padStart(2, "0")}`;
    return [
      { id: `${pair}-c`, set, pair, label: "correct" },
      { id: `${pair}-e`, set, pair, label: "tone_error" },
    ];
  }).flat();
const loose = (prefix, n, set) => Array.from({ length: n }, (_, i) => ({ id: `${prefix}${i + 1}`, set }));

const DECKS = {
  "gate block then others": [...pairCards("g", 20), ...loose("r", 10, "register"), ...loose("q", 4, "quiet")],
  "interleaved sets": [
    ...loose("w", 3, "register"),
    ...pairCards("g", 6),
    ...pairCards("m", 5, "diag_minimal"),
    ...loose("c", 6, "diag_count"),
    ...pairCards("h", 6),
  ],
  "a lone pair in its own segment": [...loose("a", 4, "register"), ...pairCards("g", 1), ...loose("b", 4, "quiet")],
  "only two pairs": pairCards("g", 2),
};

function adjacentTwins(order, deck) {
  const pairOf = new Map(deck.map((c) => [c.id, c.pair]));
  const bad = [];
  for (let i = 0; i + 1 < order.length; i++) {
    const p = pairOf.get(order[i]);
    if (p && p === pairOf.get(order[i + 1])) bad.push(`${order[i]}|${order[i + 1]}`);
  }
  return bad;
}

for (const [name, deck] of Object.entries(DECKS)) {
  test(`${name}: every card once, twins never adjacent, for every code`, () => {
    for (const code of codes) {
      const order = cardOrder(deck, code);
      assert.deepEqual([...order].sort(), deck.map((c) => c.id).sort());
      assert.deepEqual(adjacentTwins(order, deck), [], `code ${code}: ${order.join(" ")}`);
    }
  });
}

test("the same code always gives the same order; different codes give different orders", () => {
  assert.equal(new Set(codes).size, codes.length);
  const deck = DECKS["gate block then others"];
  assert.deepEqual(cardOrder(deck, "K7Q2MD"), cardOrder(deck, "K7Q2MD"));
  const distinct = new Set(codes.slice(0, 50).map((c) => cardOrder(deck, c).join(",")));
  assert.ok(distinct.size >= 45, `only ${distinct.size} distinct orders`);
});

test("unpaired cards keep their deck positions and each set stays in its block", () => {
  const deck = DECKS["gate block then others"];
  for (const code of codes.slice(0, 100)) {
    const order = cardOrder(deck, code);
    deck.forEach((card, i) => {
      if (!card.pair) assert.equal(order[i], card.id);
    });
    assert.ok(order.slice(0, 40).every((id) => id.startsWith("g")));
  }
});

test("twins are usually further apart than one card in a big gate block", () => {
  const deck = DECKS["gate block then others"];
  for (const code of codes.slice(0, 100)) {
    const order = cardOrder(deck, code);
    for (let i = 1; i <= 20; i++) {
      const p = `g${String(i).padStart(2, "0")}`;
      const gap = Math.abs(order.indexOf(`${p}-c`) - order.indexOf(`${p}-e`));
      assert.ok(gap >= 3, `code ${code}: ${p} only ${gap} apart`);
    }
  }
});

test("which twin comes first varies (the error card isn't always second)", () => {
  const deck = DECKS["gate block then others"];
  const order = cardOrder(deck, "K7Q2MD");
  const errorFirst = Array.from({ length: 20 }, (_, i) => `g${String(i + 1).padStart(2, "0")}`).filter(
    (p) => order.indexOf(`${p}-e`) < order.indexOf(`${p}-c`),
  );
  assert.ok(errorFirst.length > 3 && errorFirst.length < 17, `${errorFirst.length} of 20`);
});

test("an impossible deck (a single pair and nothing else) still returns every card", () => {
  const deck = pairCards("g", 1);
  assert.deepEqual([...cardOrder(deck, "K7Q2MD")].sort(), ["g01-c", "g01-e"]);
});

test("a pair id used by a single card (the other twin unapproved) is treated as unpaired", () => {
  const deck = [{ id: "g01-c", set: "gate", pair: "g01" }, ...loose("r", 3, "register")];
  assert.deepEqual(cardOrder(deck, "K7Q2MD"), deck.map((c) => c.id));
});
