// The prompt deck: the deck file exported as JSON (same shape as the Deck model in
// docs/s05/contracts.md §1: `{deck: {...}, card: [...]}`), served at ../deck/<id>.json.
// The sha256 is over the exact bytes fetched; the text is kept with the session so a resumed
// session reads the same deck even if a newer one has been deployed since.

export const DEFAULT_DECK_ID = "s05-v1";
export const STANDIN_ID = "standin";
const STANDIN_URL = "standin/deck.json";
const CARD_ID = /^[a-z0-9-]+$/;

export class DeckError extends Error {}

export const deckUrl = (id) => `../deck/${encodeURIComponent(id)}.json`;

/** @param {ArrayBuffer|Uint8Array} bytes */
export async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Structural checks only; the deck's content rules are the deck builder's (P3). */
export function parseDeck(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    throw new DeckError(`deck is not JSON: ${e.message}`);
  }
  if (!data?.deck || typeof data.deck.id !== "string") throw new DeckError("deck.id missing");
  if (!Array.isArray(data.card)) throw new DeckError("deck has no card list");
  const seen = new Set();
  for (const card of data.card) {
    if (typeof card?.id !== "string" || !CARD_ID.test(card.id)) throw new DeckError(`bad card id ${card?.id}`);
    if (seen.has(card.id)) throw new DeckError(`duplicate card id ${card.id}`);
    seen.add(card.id);
    if (typeof card.text !== "string" || !card.text) throw new DeckError(`card ${card.id} has no text`);
  }
  return { meta: data.deck, cards: data.card };
}

/** Cards a volunteer sees: approved ones only, unless in dev mode. */
export const shownCards = (cards, dev) => (dev ? cards : cards.filter((c) => c.status === "approved"));

/**
 * The deck a stored session was started with.
 * @returns {{id: string, sha256: string, text: string, meta: object, cards: object[]}}
 */
export function deckFromStored(stored, dev) {
  const { meta, cards } = parseDeck(stored.text);
  return { ...stored, meta, cards: shownCards(cards, dev) };
}

async function fetchBytes(fetcher, url) {
  const res = await fetcher(url, { cache: "no-cache" });
  if (!res.ok) throw new DeckError(`${url}: HTTP ${res.status}`);
  return new Uint8Array(await res.arrayBuffer());
}

/**
 * Loads deck `id` (`?deck=`), falling back to the stand-in in dev mode only.
 * @returns {Promise<{id, sha256, text, meta, cards, standin: boolean}>} `cards`: the shown cards
 */
export async function loadDeck({ id = DEFAULT_DECK_ID, dev = false, fetcher = fetch } = {}) {
  let bytes = null, standin = false;
  if (!(dev && id === STANDIN_ID)) {
    try {
      bytes = await fetchBytes(fetcher, deckUrl(id));
    } catch (e) {
      if (!dev) throw e instanceof DeckError ? e : new DeckError(`deck ${id}: ${e.message}`);
    }
  }
  if (!bytes) {
    bytes = await fetchBytes(fetcher, STANDIN_URL);
    standin = true;
  }
  const text = new TextDecoder().decode(bytes);
  const { meta, cards } = parseDeck(text);
  const shown = shownCards(cards, dev);
  if (!shown.length) throw new DeckError(`deck ${meta.id} has no approved cards`);
  return { id: meta.id, sha256: await sha256Hex(bytes), text, meta, cards: shown, standin };
}
