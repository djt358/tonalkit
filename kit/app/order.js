// The order cards are read in: deck order, except that the cards of each pair (a correct
// reading and its deliberate-error twin) are shuffled within their set's block, seeded by the
// session code, so twins are never next to each other (and usually at least three apart).
// Twins are the two cards of one (set, pair) (R66). Cards without a twin keep their deck
// positions, and no card ever leaves its set's block.

const ATTEMPTS = 200;
const WANTED_GAP = 3; // positions between twins we aim for; adjacency (gap 1) is never accepted

function seedFrom(text) {
  let h = 0x811c9dc5; // FNV-1a
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193);
  return h >>> 0;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffled(items, random) {
  const out = items.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

// How badly an order puts twins together: [adjacent twins, twins closer than WANTED_GAP].
function closeness(order, twinOf) {
  const at = new Map(order.map((id, i) => [id, i]));
  let adjacent = 0, close = 0;
  for (const [id, i] of at) {
    const twin = twinOf.get(id);
    if (!twin || id > twin) continue;
    const gap = Math.abs(at.get(twin) - i);
    if (gap === 1) adjacent++;
    if (gap < WANTED_GAP) close++;
  }
  return [adjacent, close];
}

const worse = (a, b) => a[0] > b[0] || (a[0] === b[0] && a[1] > b[1]);

// Last resort for a block too small to shuffle apart: move the second twin of each adjacent
// pair to the nearest place in the block where it doesn't touch its own twin. `order` is the
// block's slice.
function separate(order, twinOf) {
  const out = order.slice();
  const touches = (arr, id, at) =>
    [arr[at - 1], arr[at]].some((n) => n !== undefined && twinOf.get(id) === n);
  for (let guard = 0; guard < out.length; guard++) {
    const i = out.findIndex((id, k) => k + 1 < out.length && twinOf.get(id) === out[k + 1]);
    if (i < 0) break;
    const [moved] = out.splice(i + 1, 1);
    let placed = false;
    for (let d = 1; d <= out.length && !placed; d++) {
      for (const at of [i + 1 + d, i + 1 - d]) {
        if (at < 0 || at > out.length || touches(out, moved, at)) continue;
        out.splice(at, 0, moved);
        placed = true;
        break;
      }
    }
    if (!placed) {
      out.splice(i + 1, 0, moved); // impossible (e.g. a deck of one pair): leave it
      break;
    }
  }
  return out;
}

/**
 * @param {{id: string, set: string, pair?: string}[]} cards the shown cards, in deck order
 * @param {string} code the session code (the shuffle's seed)
 * @returns {string[]} card ids in reading order
 */
export function cardOrder(cards, code) {
  const byPair = new Map();
  for (const c of cards) {
    if (!c.pair) continue;
    const key = `${c.set}\0${c.pair}`;
    byPair.set(key, [...(byPair.get(key) ?? []), c.id]);
  }
  const twinOf = new Map();
  for (const ids of byPair.values()) {
    if (ids.length === 2) {
      twinOf.set(ids[0], ids[1]);
      twinOf.set(ids[1], ids[0]);
    }
  }

  const random = mulberry32(seedFrom(code));
  let order = cards.map((c) => c.id);
  // Blocks: runs of consecutive cards from the same set.
  for (let start = 0; start < cards.length; ) {
    let end = start;
    while (end < cards.length && cards[end].set === cards[start].set) end++;
    const slots = [];
    for (let i = start; i < end; i++) if (twinOf.has(order[i])) slots.push(i);
    if (slots.length >= 2) {
      const paired = slots.map((i) => order[i]);
      let best = null, bestScore = null;
      for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
        const candidate = order.slice();
        shuffled(paired, random).forEach((id, k) => (candidate[slots[k]] = id));
        const score = closeness(candidate, twinOf);
        if (!best || worse(bestScore, score)) [best, bestScore] = [candidate, score];
        if (score[1] === 0) break;
      }
      order = best;
    }
    const block = order.slice(start, end);
    if (closeness(block, twinOf)[0]) order.splice(start, end - start, ...separate(block, twinOf));
    start = end;
  }
  return order;
}
