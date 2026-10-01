// The flow: welcome -> consent -> background -> microphone check -> cards -> done -> share.
// Progress is saved after every step, so a closed tab resumes where it left off.
import { $, show, applyCopy, setMeter, setText, choiceGroup, currentScreen, onTap } from "./ui.js";
import { loadCopy, optionKey } from "./copy.js";
import { loadDeck, deckFromStored, DEFAULT_DECK_ID } from "./deck.js";
import { createSession, isoUtc, SPEAKER_OPTIONS } from "./session.js";
import { Capture, captureSupported } from "./capture.js";
import { openStore } from "./store.js";
import { buildBundle, shareBundle, bundleName } from "./export.js";
import { cardScreen } from "./cards.js";

const AMBIENT_S = 2;
const NOISY_DB = -45; // room level above this: "a bit noisy"
const SILENT_DB = -85; // below this the microphone is probably covered or not delivering

const params = new URLSearchParams(location.search);
const dev = params.get("dev") === "1";

const app = {
  t: (key) => key,
  copy: null,
  store: null,
  deck: null,
  session: null,
  capture: new Capture(),
  cards: null,
  paused: false,
  bundle: null,
  clips: new Map(), // kept takes of this page's lifetime: export still works if storage fails
  save,
  readClip,
  finish,
  pause,
};

function fatal(key, detail = "") {
  $("error-text").textContent = app.t(key);
  $("error-detail").textContent = detail;
  show("error");
}

function banner(text) {
  setText($("error-banner"), text);
}

/** Saves the session (and a kept take with it); a storage failure keeps going in memory. */
async function save(clip = null) {
  if (clip) app.clips.set(clip.id, clip.wav);
  try {
    await app.store.save(app.session, clip);
  } catch (e) {
    console.error(e);
    banner(app.t("error.storage"));
  }
}

async function readClip(id) {
  return app.clips.get(id) ?? (await app.store.getClip(id));
}

function micErrorText(e) {
  const key = { blocked: "error.mic_blocked", unsupported: "error.unsupported" }[e?.kind] ?? "error.generic";
  return app.t(key);
}

// --- screens ---------------------------------------------------------------------------------

function showConsent() {
  $("consent-text").innerHTML = app.copy.consentHtml; // escaped by the renderer
  show("consent");
}

function showBackground() {
  const box = $("background-questions");
  box.replaceChildren(
    ...Object.entries(SPEAKER_OPTIONS).map(([name, values]) =>
      choiceGroup({
        name,
        label: app.t(`background.${name}.label`),
        options: values.map((value) => ({ value, label: app.t(optionKey(name, value)) })),
        selected: app.session.speaker[name],
        onPick: (value) => (app.session.speaker[name] = value),
      }),
    ),
  );
  show("background");
}

function showMic() {
  $("mic-allow").hidden = false;
  $("mic-allow").disabled = false;
  $("mic-continue").hidden = true;
  setText($("mic-status"), "");
  setText($("mic-error"), "");
  show("mic");
}

async function openMic() {
  await app.capture.open();
  app.session.device = app.capture.device;
  await save();
}

function showCards() {
  app.cards ??= cardScreen(app);
  app.cards.render();
  show("cards");
}

async function showDone() {
  $("done-code").textContent = app.session.code;
  $("share-button").disabled = true;
  $("share-button").hidden = false;
  $("share-fallback").hidden = true;
  setText($("share-status"), "");
  show("done");
  app.capture.close(); // the recording indicator goes off: nothing more is recorded
  try {
    app.bundle = await buildBundle(app.session, async (id) => {
      const wav = await readClip(id);
      if (!wav) throw new Error(`clip ${id} missing from storage`);
      return wav;
    });
  } catch (e) {
    console.error(e);
    return banner(app.t("error.generic"));
  }
  if (navigator.canShare?.({ files: [app.bundle] })) $("share-button").disabled = false;
  else showDownload();
}

function showDownload() {
  const link = $("share-fallback");
  if (!link.href) link.href = URL.createObjectURL(app.bundle);
  link.download = app.bundle.name ?? bundleName(app.session);
  link.hidden = false;
  $("share-button").hidden = true;
}

function pause() {
  if (app.paused) return;
  app.cards?.abort();
  app.paused = true;
  setText($("pause-error"), "");
  show("pause");
}

function route() {
  if (!app.session) return show("welcome");
  const step = app.session.step;
  if (step === "consent") return showConsent();
  if (step === "background") return showBackground();
  if (step === "mic") return showMic();
  if (step === "cards") return pause(); // the microphone needs a tap to reopen
  return showDone();
}

async function finish() {
  app.session.finished_at = isoUtc();
  app.session.step = "done";
  await save();
  showDone();
}

// --- wiring ----------------------------------------------------------------------------------

function wire() {
  onTap("welcome-start", async () => {
    const { id, sha256, text, cards } = app.deck;
    app.session = createSession({ deck: { id, sha256, text }, cards, dev });
    await save();
    showConsent();
  });

  onTap("consent-agree", async () => {
    app.session.consent = { version: app.copy.consentVersion, agreed_at: isoUtc() };
    app.session.step = "background";
    await save();
    showBackground();
  });

  // Declining ends the session politely: nothing was recorded, nothing is kept.
  onTap("consent-decline", async () => {
    await app.store.clear();
    app.session = null;
    show("welcome");
  });

  onTap("background-next", async () => {
    app.session.step = "mic";
    await save();
    showMic();
  });

  onTap("mic-allow", async () => {
    const allow = $("mic-allow");
    allow.disabled = true;
    setText($("mic-error"), "");
    try {
      await openMic();
    } catch (e) {
      console.warn(e); // handled: the message tells the volunteer what to do
      setText($("mic-error"), micErrorText(e));
      allow.disabled = false;
      return;
    }
    allow.hidden = true;
    setText($("mic-status"), app.t("mic.checking"));
    const db = await app.capture.ambient(AMBIENT_S);
    $("mic-status").dataset.db = db.toFixed(1);
    setText($("mic-status"), app.t(db < SILENT_DB ? "mic.level_low" : db > NOISY_DB ? "mic.noisy" : "mic.level_ok"));
    $("mic-continue").hidden = false;
  });

  onTap("mic-continue", async () => {
    app.capture.resume();
    app.session.step = "cards";
    await save();
    showCards();
  });

  onTap("pause-resume", async () => {
    const button = $("pause-resume");
    button.disabled = true;
    setText($("pause-error"), "");
    try {
      await openMic();
    } catch (e) {
      console.warn(e); // handled: the message tells the volunteer what to do
      setText($("pause-error"), micErrorText(e));
      return;
    } finally {
      button.disabled = false;
    }
    app.paused = false;
    if (app.session.step === "mic") showMic();
    else showCards();
  });

  onTap("share-button", async () => {
    if (!app.bundle) return;
    const result = await shareBundle(app.bundle); // first thing in the tap (iOS)
    if (result === "shared") {
      await app.store.clear();
      $("share-button").hidden = true;
      setText($("share-status"), app.t("share.done"));
    } else if (result !== "cancelled") {
      showDownload();
    }
  });

  app.capture.onLevel((db) => setMeter(db));
  // Leaving the page (screen lock, another app, a call) while the microphone is open pauses
  // the kit; the take in progress, if any, is dropped.
  const micOpen = () => app.capture.ctx && ["mic", "cards"].includes(currentScreen());
  app.capture.onInterrupt = () => micOpen() && pause();
  document.addEventListener("visibilitychange", () => document.hidden && micOpen() && pause());
  window.addEventListener("pagehide", () => app.cards?.abort());
}

// --- start -----------------------------------------------------------------------------------

async function boot() {
  window.addEventListener("error", () => banner(app.t("error.generic")));
  window.addEventListener("unhandledrejection", (e) => {
    console.error(e.reason);
    banner(app.t("error.generic"));
  });

  app.copy = await loadCopy();
  app.t = app.copy.t;
  applyCopy(app.t);
  document.title = app.t("welcome.title");
  if (!captureSupported()) return fatal("error.unsupported");
  if (!dev && app.copy.consentIsStandin) return fatal("error.generic", "kit/CONSENT.md is not deployed.");

  app.store = await openStore();
  if (!app.store.persistent) banner(app.t("error.storage"));
  if (params.get("new") === "1") {
    await app.store.clear();
    params.delete("new");
    const query = params.toString();
    history.replaceState(null, "", `${location.pathname}${query ? `?${query}` : ""}`);
  }
  app.session = await app.store.loadSession();
  try {
    app.deck = app.session
      ? deckFromStored(app.session.deck, app.session.dev)
      : await loadDeck({ id: params.get("deck") ?? DEFAULT_DECK_ID, dev });
  } catch (e) {
    return fatal("error.generic", e.message);
  }
  $("dev-banner").hidden = !(dev || app.session?.dev);
  wire();
  route();
}

boot().catch((e) => {
  console.error(e);
  fatal("error.generic", String(e?.message ?? e));
});
