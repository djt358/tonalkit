// Every string the kit shows comes from kit/copy.json (P1) and kit/CONSENT.md (P2), loaded from
// the site root next to app/. The stand-ins in app/standin/ fill in when those aren't deployed
// (tests, dev), and per key when the real copy.json lacks one. A stand-in consent text is only
// ever accepted in dev mode (app.js).
import { renderMarkdown } from "./markdown.js";
import { consentVersion } from "./session.js";

// Exactly the keys of .superpowers/sdd/2026-10-01-tonekit-s05/copy-keys.md (shared with P1).
export const COPY_KEYS = [
  "welcome.title", "welcome.body", "welcome.start",
  "consent.title", "consent.agree", "consent.decline",
  "background.title", "background.intro", "background.next",
  "background.background.label", "background.background.native", "background.background.heritage",
  "background.background.learner", "background.background.prefer_not",
  "background.grew_up_hearing.label", "background.grew_up_hearing.mainland", "background.grew_up_hearing.taiwan",
  "background.grew_up_hearing.singapore_malaysia", "background.grew_up_hearing.hong_kong_macau",
  "background.grew_up_hearing.other", "background.grew_up_hearing.prefer_not",
  "background.reading.label", "background.reading.hanzi", "background.reading.hanzi_pinyin",
  "mic.title", "mic.body", "mic.allow", "mic.checking", "mic.level_ok", "mic.level_low", "mic.noisy", "mic.continue",
  "card.progress", "card.record", "card.stop", "card.play", "card.redo", "card.skip", "card.next",
  "card.note", "card.isolated_hint", "card.phrase_hint", "card.saved",
  "pause.title", "pause.body", "pause.resume",
  "done.title", "done.body", "done.code_label", "done.code_note",
  "share.button", "share.fallback", "share.done",
  "error.mic_blocked", "error.unsupported", "error.storage", "error.generic",
];

/** The copy key for a background answer: `hanzi+pinyin` -> `background.reading.hanzi_pinyin`. */
export const optionKey = (question, value) => `background.${question}.${value.replace("+", "_")}`;

/** Looks a dotted key up flat (`{"a.b": ..}`) or nested (`{"a": {"b": ..}}`). */
export function lookup(strings, key) {
  if (strings && typeof strings[key] === "string") return strings[key];
  let node = strings;
  for (const part of key.split(".")) node = node && typeof node === "object" ? node[part] : undefined;
  return typeof node === "string" ? node : undefined;
}

/** A translator over the real strings, falling back to the stand-in per key. */
export function makeT(strings, fallback) {
  return (key, vars = {}) => {
    const text = lookup(strings, key) ?? lookup(fallback, key) ?? key;
    return text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
  };
}

async function fetchOptional(fetcher, url, parse) {
  try {
    const res = await fetcher(url, { cache: "no-cache" });
    return res.ok ? await parse(res) : null;
  } catch {
    return null;
  }
}

/**
 * @param {typeof fetch} [fetcher]
 * @returns {Promise<{t: Function, consentHtml: string, consentVersion: string,
 *   consentIsStandin: boolean, copyIsStandin: boolean}>}
 *   The app refuses to run outside dev mode on a stand-in consent text.
 */
export async function loadCopy(fetcher = fetch) {
  const [real, standin, consent, standinConsent] = await Promise.all([
    fetchOptional(fetcher, "../copy.json", (r) => r.json()),
    fetchOptional(fetcher, "standin/copy.json", (r) => r.json()),
    fetchOptional(fetcher, "../CONSENT.md", (r) => r.text()),
    fetchOptional(fetcher, "standin/CONSENT.md", (r) => r.text()),
  ]);
  const markdown = consent ?? standinConsent ?? "";
  return {
    t: makeT(real, standin),
    consentHtml: renderMarkdown(markdown),
    consentVersion: consentVersion(markdown),
    consentIsStandin: consent === null,
    copyIsStandin: real === null,
  };
}
