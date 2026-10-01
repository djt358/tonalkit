// The session record: code, background answers (contract enums), consent, timestamps, and the
// per-card progress that the export turns into session.json (docs/s05/contracts.md §2).
import { cardOrder } from "./order.js";

export const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O/1/I
export const CODE_LENGTH = 6;
const CODE_RE = new RegExp(`^[${CODE_ALPHABET}]{${CODE_LENGTH}}$`);

export const SPEAKER_OPTIONS = {
  background: ["native", "heritage", "learner", "prefer_not"],
  grew_up_hearing: ["mainland", "taiwan", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not"],
  reading: ["hanzi", "hanzi+pinyin"],
};
export const DEFAULT_SPEAKER = Object.freeze({
  background: "prefer_not",
  grew_up_hearing: "prefer_not",
  reading: "hanzi",
});

const randomBytes = (n) => crypto.getRandomValues(new Uint8Array(n));

/** Six unambiguous characters; 256 % 32 == 0, so `byte & 31` is unbiased. */
export function newCode(random = randomBytes) {
  return Array.from(random(CODE_LENGTH), (b) => CODE_ALPHABET[b & 31]).join("");
}

export const isCode = (text) => CODE_RE.test(text);

/** "2026-10-03T18:02:11Z" */
export const isoUtc = (date = new Date()) => date.toISOString().replace(/\.\d{3}Z$/, "Z");

/** The version in CONSENT.md's first line (`<!-- consent: v1 -->`), else "v1". */
export function consentVersion(markdown) {
  const first = markdown.split(/\r?\n/, 1)[0] ?? "";
  return first.match(/^<!--\s*consent:\s*(\S+?)\s*-->/)?.[1] ?? "v1";
}

/**
 * @param {{deck: {id: string, sha256: string, text: string}, cards: object[], dev: boolean,
 *          now?: Date, code?: string}} args  `cards`: the shown cards, in deck order
 */
export function createSession({ deck, cards, dev, now = new Date(), code = newCode() }) {
  return {
    v: 1,
    code,
    deck,
    dev,
    started_at: isoUtc(now),
    finished_at: null,
    consent: null,
    speaker: { ...DEFAULT_SPEAKER },
    device: null,
    order: cardOrder(cards, code),
    index: 0,
    cards: {}, // card id -> {takes, kept, skipped, duration_s, peak, quiet}
    step: "consent", // consent | background | mic | cards | done
  };
}

/** Progress for one card (created on first use). */
export function cardState(session, id) {
  return (session.cards[id] ??= { takes: 0, kept: false, skipped: false, duration_s: 0, peak: 0, quiet: false });
}
