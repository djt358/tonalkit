// The card screen: one card at a time, record / stop / play / redo / skip / next.
import { $, setText, currentScreen } from "./ui.js";
import { cardState } from "./session.js";
import { processTake } from "./take.js";

const MAX_TAKE_S = 30; // a forgotten Stop ends the take here (it is kept, not thrown away)
const LONG_TEXT = 6; // characters; longer cards get a smaller font

/**
 * @param {object} app the shared app context: {t, session, deck, store, capture, save, finish, pause}
 */
export function cardScreen(app) {
  const byId = new Map(app.deck.cards.map((c) => [c.id, c]));
  const audio = new Audio();
  let recordingId = null;
  let busy = false;
  let maxTimer = null;
  let clip = { id: null, url: null }; // the kept take of the card on screen, ready to play

  const currentId = () => app.session.order[app.session.index];

  function setClip(id, wav) {
    if (clip.url) URL.revokeObjectURL(clip.url);
    clip = { id, url: wav ? URL.createObjectURL(new Blob([wav], { type: "audio/wav" })) : null };
  }

  function stopPlayback() {
    audio.pause();
  }

  function update() {
    const id = currentId();
    const state = app.session.cards[id];
    const kept = Boolean(state?.kept);
    const recording = recordingId === id;
    const record = $("card-record");
    record.textContent = app.t(recording ? "card.stop" : "card.record");
    record.classList.toggle("recording", recording);
    record.hidden = kept && !recording;
    record.disabled = busy;
    $("card-play").hidden = !kept || recording;
    $("card-redo").hidden = !kept || recording;
    $("card-play").disabled = busy || !clip.url;
    $("card-redo").disabled = busy;
    const skip = $("card-skip");
    skip.hidden = kept || recording;
    skip.disabled = busy;
    skip.setAttribute("aria-pressed", String(Boolean(state?.skipped)));
    $("card-next").disabled = busy || recording || !(kept || state?.skipped);
    let status = "";
    if (kept && !recording) status = app.t("card.saved") + (state.quiet ? ` ${app.t("mic.level_low")}` : "");
    $("card-status").textContent = status;
  }

  async function render() {
    const id = currentId();
    const card = byId.get(id);
    stopPlayback();
    setClip(id, null);
    $("card-progress").textContent = app.t("card.progress", { n: app.session.index + 1, total: app.session.order.length });
    const text = $("card-text");
    text.textContent = card.text;
    text.classList.toggle("long", [...card.text].length > LONG_TEXT);
    setText($("card-pinyin"), app.session.speaker.reading === "hanzi+pinyin" ? card.pinyin ?? "" : "");
    const hintKey = { isolated: "card.isolated_hint", phrase: "card.phrase_hint" }[card.context];
    setText($("card-hint"), hintKey ? app.t(hintKey) : "");
    setText($("card-note"), card.prompt_note ? app.t("card.note", { note: card.prompt_note }) : "");
    update();
    if (app.session.cards[id]?.kept) {
      const wav = await app.store.getClip(id);
      if (currentId() === id && !clip.url) setClip(id, wav);
      update();
    }
  }

  function start() {
    app.capture.resume(); // inside the tap (iOS)
    if (!app.capture.live) return app.pause();
    stopPlayback();
    recordingId = currentId();
    app.capture.start();
    maxTimer = setTimeout(stop, MAX_TAKE_S * 1000);
    update();
  }

  async function stop() {
    clearTimeout(maxTimer);
    const id = recordingId;
    if (!id || busy) return;
    busy = true;
    update();
    try {
      const samples = await app.capture.stop();
      if (samples.length && recordingId === id) {
        const take = processTake(samples, app.capture.rate);
        const state = cardState(app.session, id);
        Object.assign(state, {
          takes: state.takes + 1,
          kept: true,
          skipped: false,
          duration_s: take.duration_s,
          peak: take.peak,
          quiet: take.quiet,
        });
        await app.save({ id, wav: take.wav });
        if (currentId() === id) setClip(id, take.wav);
      }
    } finally {
      recordingId = null;
      busy = false;
      if (currentScreen() === "cards") update();
    }
  }

  /** An interruption (another app, the screen locking) throws the take in progress away. */
  function abort() {
    clearTimeout(maxTimer);
    if (recordingId) app.capture.abort();
    recordingId = null;
    stopPlayback();
  }

  $("card-record").addEventListener("click", () => (recordingId ? stop() : start()));
  $("card-redo").addEventListener("click", start);
  $("card-play").addEventListener("click", () => {
    if (!clip.url) return;
    audio.src = clip.url;
    audio.currentTime = 0;
    audio.play().catch(() => {});
  });
  $("card-skip").addEventListener("click", async () => {
    cardState(app.session, currentId()).skipped = true;
    update();
    await app.save();
  });
  $("card-next").addEventListener("click", async () => {
    if ($("card-next").disabled) return;
    $("card-next").disabled = true; // a double tap must not skip a card
    stopPlayback();
    app.session.index += 1;
    if (app.session.index >= app.session.order.length) return app.finish();
    await app.save();
    render();
  });

  return { render, abort };
}
