// Every string the kit shows comes from kit/copy.json (P1) and kit/CONSENT.md (P2), loaded from
// the site root next to app/. The stand-ins in app/standin/ fill in when those aren't deployed
// (tests, dev), and per key when the real copy.json lacks one. A consent text that isn't the
// real, versioned one is only ever accepted in dev mode (app.js).
import { renderMarkdown } from "./markdown.js";
import { consentVersion } from "./session.js";

// Exactly the keys of .superpowers/sdd/2026-10-01-tonekit-s05/copy-keys.md (shared with P1).
export const COPY_KEYS = [
  "welcome.title", "welcome.body", "welcome.start",
  "consent.title", "consent.agree", "consent.decline", "consent.declined",
  "background.title", "background.intro", "background.next",
  "background.background.label", "background.background.native", "background.background.heritage",
  "background.background.learner", "background.background.prefer_not",
  "background.grew_up_hearing.label", "background.grew_up_hearing.mainland", "background.grew_up_hearing.taiwan",
  "background.grew_up_hearing.singapore_malaysia", "background.grew_up_hearing.hong_kong_macau",
  "background.grew_up_hearing.other", "background.grew_up_hearing.prefer_not",
  "background.reading.label", "background.reading.hanzi", "background.reading.hanzi_pinyin",
  "background.script.label", "background.script.simplified", "background.script.traditional",
  "mic.title", "mic.body", "mic.allow", "mic.checking", "mic.level_ok", "mic.level_low", "mic.noisy", "mic.continue",
  "card.progress", "card.record", "card.stop", "card.play", "card.redo", "card.skip", "card.next",
  "card.note", "card.isolated_hint", "card.phrase_hint", "card.saved",
  "card.finish_early", "card.finish_early_confirm",
  "pause.title", "pause.body", "pause.resume",
  "done.title", "done.body", "done.code_label", "done.code_note",
  "done.delete", "done.delete_confirm", "done.deleted",
  "share.button", "share.fallback", "share.done", "share.again",
  "error.mic_blocked", "error.unsupported", "error.storage", "error.generic", "error.in_app_browser",
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

/** Why a consent text can't be shown to volunteers, or null when it can. */
function consentProblem(deployed, version) {
  if (deployed === null) return "kit/CONSENT.md is not deployed.";
  if (version === null) return "kit/CONSENT.md has no <!-- consent: vN --> marker on its first line.";
  if (version === "standin") return "kit/CONSENT.md is the stand-in text.";
  return null;
}

/**
 * @param {typeof fetch} [fetcher]
 * @returns {Promise<{t: Function, consentHtml: string, consentVersion: string,
 *   consentProblem: string|null, copyIsStandin: boolean}>}
 *   The app refuses to run outside dev mode when there is a consentProblem.
 */
export async function loadCopy(fetcher = fetch) {
  const [real, standin, consent, standinConsent] = await Promise.all([
    fetchOptional(fetcher, "../copy.json", (r) => r.json()),
    fetchOptional(fetcher, "standin/copy.json", (r) => r.json()),
    fetchOptional(fetcher, "../CONSENT.md", (r) => r.text()),
    fetchOptional(fetcher, "standin/CONSENT.md", (r) => r.text()),
  ]);
  const markdown = consent ?? standinConsent ?? "";
  const version = consentVersion(markdown);
  return {
    t: makeT(real, standin),
    consentHtml: renderMarkdown(markdown),
    consentVersion: version ?? "unmarked", // dev mode only: volunteers never get this far
    consentProblem: consentProblem(consent, consentVersion(consent ?? "")),
    copyIsStandin: real === null,
  };
}
