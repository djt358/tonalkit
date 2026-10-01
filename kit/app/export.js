// The session bundle (docs/s05/contracts.md §2): session.json + clips/<card>.wav in a zip named
// tonekit-<deck id>-<code>.zip, handed to the share sheet (or downloaded where sharing files
// isn't available).
import { makeZip } from "./zip.js";

export const SCHEMA = "tonekit.session.v1";

/** session.json, exactly the contract's fields: clips and skipped cards in reading order. */
export function sessionJson(session) {
  const clips = [];
  const skipped = [];
  for (const id of session.order) {
    const card = session.cards[id];
    if (card?.kept) {
      clips.push({ card: id, file: `clips/${id}.wav`, takes: card.takes, duration_s: card.duration_s, peak: card.peak });
    } else if (card?.skipped) {
      skipped.push(id);
    }
  }
  const { user_agent, input_sample_rate, constraints } = session.device ?? {};
  return {
    schema: SCHEMA,
    deck: { id: session.deck.id, sha256: session.deck.sha256 },
    session: session.code,
    started_at: session.started_at,
    finished_at: session.finished_at,
    consent: { version: session.consent.version, agreed_at: session.consent.agreed_at },
    speaker: {
      background: session.speaker.background,
      grew_up_hearing: session.speaker.grew_up_hearing,
      reading: session.speaker.reading,
    },
    device: { user_agent, input_sample_rate, constraints },
    clips,
    skipped,
  };
}

export const bundleName = (session) => `tonekit-${session.deck.id}-${session.code}.zip`;

/**
 * @param {object} session a finished session
 * @param {(id: string) => Promise<Uint8Array>} readClip the kept WAV of a card
 * @returns {Promise<File|Blob>} a File where the platform has one (the share sheet needs it)
 */
export async function buildBundle(session, readClip) {
  const json = sessionJson(session);
  const entries = [{ name: "session.json", data: new TextEncoder().encode(JSON.stringify(json, null, 2) + "\n") }];
  for (const clip of json.clips) entries.push({ name: clip.file, data: await readClip(clip.card) });
  const zip = makeZip(entries, new Date(session.finished_at ?? Date.now()));
  return typeof File === "function" ? new File([zip], bundleName(session), { type: "application/zip" }) : zip;
}

/**
 * Opens the share sheet with the bundle. Must run inside the tap's handler, without awaiting
 * anything first (iOS drops the user gesture across async work).
 * @returns {Promise<"shared"|"cancelled"|"unsupported"|"failed">}
 */
export async function shareBundle(file, nav = globalThis.navigator) {
  if (!nav?.share || !nav.canShare?.({ files: [file] })) return "unsupported";
  try {
    await nav.share({ files: [file] });
    return "shared";
  } catch (e) {
    return e?.name === "AbortError" ? "cancelled" : "failed";
  }
}
