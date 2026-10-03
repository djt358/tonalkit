// The session record: code, background answers (contract enums), consent, timestamps, and the
// per-card progress that the export turns into session.json (docs/s05/contracts.md §2).
import { cardOrder } from "./order.js";

export const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O/1/I
export const CODE_LENGTH = 6;
const CODE_RE = new RegExp(`^[${CODE_ALPHABET}]{${CODE_LENGTH}}$`);

// The background questions in the order they're asked. `script` (R74) has no prefer_not: the
// cards have to be shown in one script or the other.
export const SPEAKER_OPTIONS = {
  background: ["native", "heritage", "learner", "prefer_not"],
  grew_up_hearing: ["mainland", "taiwan", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not"],
  script: ["simplified", "traditional"],
  reading: ["hanzi", "hanzi+pinyin"],
};
export const DEFAULT_SPEAKER = Object.freeze({
  background: "prefer_not",
  grew_up_hearing: "prefer_not",
  script: "simplified",
  reading: "hanzi",
});

const TRADITIONAL_REGIONS = new Set(["taiwan", "hong_kong_macau"]);

/** The script preselected for someone who grew up hearing Mandarin in `region`, until they pick one. */
export const defaultScript = (region) => (TRADITIONAL_REGIONS.has(region) ? "traditional" : "simplified");

const randomBytes = (n) => crypto.getRandomValues(new Uint8Array(n));

/** Six unambiguous characters; 256 % 32 == 0, so `byte & 31` is unbiased. */
export function newCode(random = randomBytes) {
  return Array.from(random(CODE_LENGTH), (b) => CODE_ALPHABET[b & 31]).join("");
}

export const isCode = (text) => CODE_RE.test(text);

/** "2026-10-03T18:02:11Z" */
export const isoUtc = (date = new Date()) => date.toISOString().replace(/\.\d{3}Z$/, "Z");

/** The version in CONSENT.md's first line (`<!-- consent: v1 -->`), else null. */
export function consentVersion(markdown) {
  const first = markdown.split(/\r?\n/, 1)[0] ?? "";
  return first.match(/^<!--\s*consent:\s*(\S+?)\s*-->/)?.[1] ?? null;
}

/**
 * The microphone a session records with is the first one opened: session.json has one device,
 * so a later change (AirPods connected mid-session) keeps the first values and is only reported.
 * Every take is still resampled from the rate it was actually captured at.
 * @returns {{device: object, change: string|null}}
 */
export function sessionDevice(stored, current) {
  if (!stored) return { device: current, change: null };
  const changes = [];
  if (stored.input_sample_rate !== current.input_sample_rate) {
    changes.push(`input_sample_rate ${stored.input_sample_rate} -> ${current.input_sample_rate}`);
  }
  for (const [key, value] of Object.entries(current.constraints ?? {})) {
    if (stored.constraints?.[key] !== value) changes.push(`${key} ${stored.constraints?.[key]} -> ${value}`);
  }
  return { device: stored, change: changes.length ? changes.join(", ") : null };
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
    script_chosen: false, // until the person taps a script, it follows grew_up_hearing
    device: null,
    order: cardOrder(cards, code),
    index: 0,
    cards: {}, // card id -> {takes, kept, skipped, duration_s, peak, quiet}
    step: "consent", // consent | background | mic | cards | done
    shared: false, // the share sheet reported success (R77)
    downloaded: false, // the fallback download link was tapped (R90)
  };
}

/** R90: before the bundle was shared or downloaded, a delete says nothing has been sent. */
export const deleteConfirmKey = (session) =>
  session.shared || session.downloaded ? "done.delete_confirm" : "done.delete_confirm_unsent";

/** Progress for one card (created on first use). */
export function cardState(session, id) {
  return (session.cards[id] ??= { takes: 0, kept: false, skipped: false, duration_s: 0, peak: 0, quiet: false });
}

/** Whether any card has a kept take (finishing early is offered from then on). */
export const hasKeptTake = (session) => Object.values(session.cards).some((c) => c.kept);

/** Finishing early: every card without a kept take is skipped. */
export function skipRemaining(session) {
  for (const id of session.order) {
    const state = cardState(session, id);
    if (!state.kept) state.skipped = true;
  }
}
