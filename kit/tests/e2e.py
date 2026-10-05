#!/usr/bin/env python3
"""The kit end to end in headless Chromium, with the shared fixture as the microphone.

Assembles the site as Pages does, serves it locally, and walks volunteers' sessions in dev mode
on the stand-in deck:
- the full session in traditional characters: consent, background, microphone check, six cards
  (a reload, an interruption, a skip and a redo on the way), the download, then the share sheet,
  "Send again" and "Delete from this phone" (R77, R90), card notes in the reader's script (R88);
- finishing early after one card;
- a blocked microphone, an in-app browser (R84), declining consent, and volunteer mode.
Every request must go to the test server, the microphone is never asked for before consent,
nothing may break the page's Content-Security-Policy, and no screen has a text field. The bundles are checked against the
contract (check_bundle.py) and for fidelity (every clip is the fixture's speech, at the right
pitch and speed).

All generated audio stays in a temporary directory.
"""

from __future__ import annotations

import functools
import http.server
import io
import json
import re
import struct
import subprocess
import sys
import tempfile
import threading
import wave
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import expect, sync_playwright
from scipy.signal import correlate, resample_poly

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "kit"
FIXTURE = ROOT / "fixtures" / "spoken-413.wav"
MIC_RATE = 48000
TAKE_S = 1.5
MIN_CORRELATION = 0.9
# P1/P2's content and P3's deck may not be merged yet: the app falls back to its stand-ins.
OPTIONAL_FILES = ("/copy.json", "/CONSENT.md", "/deck/s05-v1.json")
STANDIN = "?dev=1&deck=standin"
# What the stand-in deck's cards show in each script (R74); g02 differs between the two.
TRADITIONAL = {"一杯水", "一杯睡", "買書", "賣書", "一", "不對"}
SIMPLIFIED = {"一杯水", "一杯睡", "买书", "卖书", "一", "不对"}
TWINS = [{"一杯水", "一杯睡"}, {"買書", "賣書"}, {"买书", "卖书"}]
# The note under each card, per script (R88), read from the stand-in deck the app uses.
NOTES = {}
for _card in json.loads((KIT / "app" / "standin" / "deck.json").read_text())["card"]:
    NOTES["simplified", _card["text"]] = _card["prompt_note"]
    NOTES["traditional", _card.get("text_traditional") or _card["text"]] = (
        _card.get("prompt_note_traditional") or _card["prompt_note"]
    )
WECHAT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x18003137) NetType/WIFI Language/zh_CN"
)


def read_fixture() -> tuple[np.ndarray, int]:
    """The fixture is WAVE_FORMAT_EXTENSIBLE float32 mono; returns (samples, rate)."""
    data = FIXTURE.read_bytes()
    pos, fmt = 12, None
    while pos + 8 <= len(data):
        chunk, size = (
            data[pos : pos + 4],
            struct.unpack("<I", data[pos + 4 : pos + 8])[0],
        )
        body = data[pos + 8 : pos + 8 + size]
        if chunk == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif chunk == b"data":
            channels, rate, bits = fmt[1], fmt[2], fmt[5]
            assert channels == 1 and bits == 32, fmt
            return np.frombuffer(body, dtype="<f4").astype(np.float64), rate
        pos += 8 + size + (size & 1)
    raise ValueError("fixture has no data chunk")


def resample(x: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    g = np.gcd(rate_in, rate_out)
    return resample_poly(x, rate_out // g, rate_in // g)


def speech_loop() -> np.ndarray:
    """What the fake microphone plays, at 16 kHz: the fixture three times with short pauses.

    Chromium loops the file, so any 1.5 s window holds speech.
    """
    speech, rate = read_fixture()
    assert rate == 16000
    gap = np.zeros(int(0.25 * rate))
    return np.concatenate([speech, gap, speech, gap, speech, gap])


def write_fake_mic(path: Path) -> None:
    """The loop at 48 kHz, 16-bit PCM mono (what --use-file-for-fake-audio-capture reads), with a
    -60 dBFS noise floor so the room check and the trimmer see a realistic background."""
    x = resample(speech_loop(), 16000, MIC_RATE)
    rng = np.random.default_rng(413)
    x = x + rng.normal(0, 10 ** (-60 / 20), len(x))
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(MIC_RATE)
        w.writeframes(pcm.tobytes())


def best_correlation(clip: np.ndarray, reference: np.ndarray) -> float:
    """Max normalised cross-correlation of the clip's loudest second against the (doubled)
    reference loop: ~1.0 when the clip is the reference's speech at the same pitch and speed."""
    frame = 1600
    energies = [
        np.sum(clip[i : i + frame] ** 2)
        for i in range(0, max(1, len(clip) - frame), frame)
    ]
    start = int(np.argmax(energies)) * frame
    probe = clip[max(0, start - 4000) : start + 12000]
    probe = probe - probe.mean()
    ref = np.concatenate([reference, reference])
    n = len(probe)
    corr = correlate(ref, probe, mode="valid", method="fft")
    energy = np.concatenate([[0.0], np.cumsum(ref**2)])
    window = energy[n:] - energy[:-n]
    norm = np.sqrt(np.maximum(window, 0) * np.sum(probe**2)) + 1e-12
    return float(np.max(corr / norm))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the test output readable
        pass


def serve(directory: Path) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def record(page, seconds: float = TAKE_S) -> None:
    page.click("#card-record")
    expect(page.locator("#card-record")).to_have_class(re.compile(r"\brecording\b"))
    page.wait_for_timeout(seconds * 1000)
    page.click("#card-record")
    expect(page.locator("#card-next")).to_be_enabled(timeout=10_000)
    expect(page.locator("#card-play")).to_be_visible()


def watch(page, problems: list[str]) -> None:
    """Page errors, console errors (CSP violations among them) and failed requests (other than
    optional content) are problems."""
    page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
    page.on(
        "console",
        lambda m: (
            m.type == "error"
            and not m.text.startswith("Failed to load resource")  # judged by URL below
            and problems.append(f"console: {m.text}")
        ),
    )
    page.on(
        "response",
        lambda r: (
            r.status >= 400
            and not r.url.endswith(OPTIONAL_FILES)
            and problems.append(f"HTTP {r.status}: {r.url}")
        ),
    )


# Runs before the kit's own scripts in every page: the microphone must never be asked for before
# the person taps "I agree" (in this tab, across reloads), and CSP violations are recorded.
GUARD = """
(() => {
  const KEY = "__e2e_consented";
  window.__cspViolations = [];
  document.addEventListener("securitypolicyviolation", (e) =>
    window.__cspViolations.push(`${e.violatedDirective} ${e.blockedURI}`));
  document.addEventListener("click", (e) => {
    if (e.target.closest && e.target.closest("#consent-agree")) sessionStorage.setItem(KEY, "1");
  }, true);
  // R77: the page may say "Send again" only once the store holds it. Count the writes in flight
  // (readwrite transactions not yet complete) and note how many there were whenever the share
  // button's text changed.
  window.__writes = 0;
  window.__shareTextChanges = [];
  const transaction = IDBDatabase.prototype.transaction;
  IDBDatabase.prototype.transaction = function (stores, mode, ...rest) {
    const tx = transaction.call(this, stores, mode, ...rest);
    if (mode === "readwrite") {
      window.__writes++;
      for (const type of ["complete", "abort"]) tx.addEventListener(type, () => window.__writes--, {once: true});
    }
    return tx;
  };
  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("share-button");
    new MutationObserver(() =>
      window.__shareTextChanges.push({text: button.textContent, writes: window.__writes}),
    ).observe(button, {childList: true, characterData: true, subtree: true});
  });
  // The kit never asks for free text (PROMISES: no names, no notes): no text field on any screen,
  // in the page as parsed or as the app builds it.
  const TEXT_FIELDS = "input[type=text], input:not([type]), textarea, [contenteditable]";
  window.__textFields = [];
  const scan = (node) => {
    if (node.nodeType !== 1) return;
    for (const el of [node, ...node.querySelectorAll(TEXT_FIELDS)]) {
      if (el.matches(TEXT_FIELDS)) window.__textFields.push(`<${el.localName}> in #${el.closest("section")?.id}`);
    }
  };
  new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "attributes") scan(r.target);
      else r.addedNodes.forEach(scan);
    }
  }).observe(document, {childList: true, subtree: true, attributes: true, attributeFilter: ["contenteditable", "type"]});
  document.addEventListener("DOMContentLoaded", () => scan(document.documentElement));
  // Playback of a take: through the capture's audio context (Web Audio), or the audio element
  // fallback (a blob: URL, under the CSP's media-src).
  window.__played = 0;
  const startSource = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function (...args) {
    const out = startSource.apply(this, args);
    window.__played++;
    return out;
  };
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    const playing = play.call(this);
    playing.then(() => window.__played++, (e) => console.error(`e2e: playback failed: ${e}`));
    return playing;
  };
  const media = navigator.mediaDevices;
  if (!media || !media.getUserMedia) return;
  const real = media.getUserMedia.bind(media);
  media.getUserMedia = (...args) => {
    if (sessionStorage.getItem(KEY) !== "1") {
      window.__micBeforeConsent = true;
      console.error("e2e: getUserMedia was called before consent");
    }
    return real(...args);
  };
})();
"""


def origin(url: str) -> str | None:
    """A request's origin; None for data: URLs, which never leave the page."""
    if url.startswith("data:"):
        return None
    parts = urlsplit(url.removeprefix("blob:"))
    return f"{parts.scheme}://{parts.netloc}"


def new_context(
    browser, base: str, problems: list[str], before: tuple[str, ...] = (), **options
):
    """A browser context whose every request must go to the test server, with GUARD installed
    (after `before`, so it wraps whatever getUserMedia those scripts set up)."""
    context = browser.new_context(**options)
    for script in (*before, GUARD):
        context.add_init_script(script)
    server = origin(base)
    context.on(
        "request",
        lambda r: (
            origin(r.url) not in (None, server)
            and problems.append(f"request to another origin: {r.url}")
        ),
    )
    return context


def page_clean(page, problems: list[str]) -> None:
    """At the end of a page's flow: no CSP violation, no text field, no microphone before consent."""
    violations = page.evaluate("window.__cspViolations")
    if violations:
        problems.append(f"CSP violations: {violations}")
    fields = page.evaluate("window.__textFields")
    if fields:
        problems.append(f"text fields: {fields}")
    if page.evaluate("window.__micBeforeConsent === true"):
        problems.append("getUserMedia was called before consent")


# Stands in for the iOS share sheet: records what it was given, then succeeds.
FAKE_SHARE = """
navigator.canShare = (data) => Boolean(data && data.files && data.files.length);
navigator.share = async (data) => {
  const f = data.files[0];
  window.__shared = {name: f.name, type: f.type, size: f.size};
  window.__shares = (window.__shares || 0) + 1;
};
"""

# iOS Safari's track.getSettings(): no noiseSuppression, no autoGainControl (R83).
SAFARI_SETTINGS = """
const getSettings = MediaStreamTrack.prototype.getSettings;
MediaStreamTrack.prototype.getSettings = function () {
  const { noiseSuppression, autoGainControl, ...reported } = getSettings.call(this);
  return reported;
};
"""

# Simulates the screen locking / switching apps: the page becomes hidden.
HIDE_PAGE = """
Object.defineProperty(document, "hidden", {value: true, configurable: true});
document.dispatchEvent(new Event("visibilitychange"));
Object.defineProperty(document, "hidden", {value: false, configurable: true});
"""


# What the store holds, read straight from IndexedDB (the page must have opened it already).
STORED_SESSION = """
async () => new Promise((resolve, reject) => {
  const open = indexedDB.open("tonekit-kit");
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result;
    const get = db.transaction("session").objectStore("session").get("current");
    get.onsuccess = () => { db.close(); resolve(get.result ?? null); };
    get.onerror = () => reject(get.error);
  };
})
"""


def stored_session(page) -> dict | None:
    return page.evaluate(STORED_SESSION)


def delete_confirm_text(page) -> str:
    """Taps "Delete from this phone", reads the native confirm, and cancels it."""
    seen: list[str] = []
    page.once("dialog", lambda d: (seen.append(d.message), d.dismiss()))
    page.click("#done-delete")
    assert len(seen) == 1, seen
    return seen[0]


def start_session(page, base: str) -> None:
    """Welcome and consent, from a fresh page."""
    page.goto(base + STANDIN)
    expect(page.locator("#dev-banner")).to_be_visible()
    page.click("#welcome-start")
    expect(page.locator("#screen-consent")).to_be_visible()
    # P12's CONSENT.md headings are ## (rendered h3), the stand-in's # (h2).
    expect(page.locator("#consent-text :is(h2, h3)").first).to_be_visible()
    page.click("#consent-agree")
    expect(page.locator("#screen-background")).to_be_visible()


def check_microphone(page) -> None:
    expect(page.locator("#screen-mic")).to_be_visible()
    page.click("#mic-allow")
    expect(page.locator("#mic-continue")).to_be_visible(timeout=10_000)
    # The fake microphone is a quiet room (-60 dBFS) with speech: the check says it sounds good.
    status = page.locator("#mic-status")
    expect(status).to_have_attribute("data-verdict", "ok")
    expect(status).to_have_text(copy_text("mic.level_ok"))
    page.click("#mic-continue")


def card_face(page, faces: set[str], lang: str) -> str:
    """The card on screen: its text must be one of `faces`, tagged `lang`, with the deck's note
    for that script under it (R88: 睡覺 for a traditional reader, 睡觉 for a simplified one)."""
    text = page.locator("#card-text")
    expect(text).not_to_be_empty()
    expect(text).to_have_attribute("lang", lang)
    shown = text.inner_text()
    assert shown in faces, f"{shown!r} is not one of {sorted(faces)}"
    script = "traditional" if lang == "zh-Hant" else "simplified"
    note = NOTES[script, shown]
    note_box = page.locator("#card-note")
    if note:
        expect(note_box).to_have_text(copy_text("card.note").replace("{note}", note))
        expect(note_box).to_have_attribute("lang", lang)
    else:
        expect(note_box).to_be_hidden()
    if shown == "一杯睡":
        assert ("睡覺" in note) == (script == "traditional") and ("睡觉" in note) == (
            script == "simplified"
        ), note
    return shown


def download_bundle(page, tmp: Path) -> tuple[Path, str]:
    expect(page.locator("#screen-done")).to_be_visible()
    code = page.locator("#done-code").inner_text()
    assert re.fullmatch(r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}", code), code
    fallback = page.locator("#share-fallback")
    expect(fallback).to_be_visible(timeout=10_000)  # no Web Share in headless Chromium
    with page.expect_download() as download:
        fallback.click()
    bundle = tmp / download.value.suggested_filename
    download.value.save_as(bundle)
    assert bundle.name == f"tonekit-standin-v1-{code}.zip", bundle.name
    return bundle, code


def volunteer_session(
    browser, base: str, tmp: Path, problems: list[str]
) -> tuple[Path, list[str]]:
    """The whole flow in traditional characters; returns the bundle and the cards shown."""
    shown: list[str] = []
    context = new_context(browser, base, problems, accept_downloads=True)
    page = context.new_page()
    watch(page, problems)
    start_session(page, base)

    for question, value in (
        ("background", "prefer_not"),
        ("grew_up_hearing", "prefer_not"),
        ("script", "simplified"),
        ("reading", "hanzi"),
    ):
        expect(page.locator(f'#q-{question} [data-value="{value}"]')).to_have_attribute(
            "aria-checked", "true"
        )
    page.click('#q-background [data-value="heritage"]')
    page.click('#q-grew_up_hearing [data-value="taiwan"]')
    # Until the script is picked, it follows grew_up_hearing (Taiwan: traditional).
    expect(page.locator('#q-script [data-value="traditional"]')).to_have_attribute(
        "aria-checked", "true"
    )
    page.click('#q-script [data-value="traditional"]')
    page.click(
        '#q-grew_up_hearing [data-value="mainland"]'
    )  # an explicit pick now stays
    expect(page.locator('#q-script [data-value="traditional"]')).to_have_attribute(
        "aria-checked", "true"
    )
    page.click('#q-grew_up_hearing [data-value="taiwan"]')
    page.click('#q-reading [data-value="hanzi+pinyin"]')
    page.click("#background-next")
    check_microphone(page)

    # Card 1, then close-and-reopen: the session resumes on the same card, take kept.
    expect(page.locator("#card-progress")).to_have_text("1 of 6")
    expect(page.locator("#card-pinyin")).to_be_visible()
    expect(page.locator("#card-finish")).to_be_hidden()  # nothing kept yet
    shown.append(card_face(page, TRADITIONAL, "zh-Hant"))
    record(page)
    expect(page.locator("#card-finish")).to_be_visible()
    page.click("#card-play")
    page.wait_for_function("() => window.__played === 1", timeout=10_000)
    page.reload()
    expect(page.locator("#screen-pause")).to_be_visible()
    page.click("#pause-resume")
    expect(page.locator("#card-progress")).to_have_text("1 of 6")
    expect(page.locator("#card-play")).to_be_visible()
    assert card_face(page, TRADITIONAL, "zh-Hant") == shown[0]
    page.click("#card-next")

    # Card 2: the page is hidden mid-take (screen locked): the take is dropped, the kit pauses,
    # and after resuming the card is recorded again.
    expect(page.locator("#card-progress")).to_have_text("2 of 6")
    shown.append(card_face(page, TRADITIONAL, "zh-Hant"))
    page.click("#card-record")
    page.wait_for_timeout(500)
    page.evaluate(HIDE_PAGE)
    expect(page.locator("#screen-pause")).to_be_visible()
    page.click("#pause-resume")
    expect(page.locator("#card-progress")).to_have_text("2 of 6")
    expect(page.locator("#card-next")).to_be_disabled()
    expect(page.locator("#card-record")).not_to_have_class(re.compile(r"\brecording\b"))
    record(page)
    page.click("#card-next")

    # Card 3: skipped. Card 4: recorded, then redone. Cards 5 and 6: recorded.
    expect(page.locator("#card-progress")).to_have_text("3 of 6")
    shown.append(card_face(page, TRADITIONAL, "zh-Hant"))
    page.click("#card-skip")
    page.click("#card-next")
    expect(page.locator("#card-progress")).to_have_text("4 of 6")
    shown.append(card_face(page, TRADITIONAL, "zh-Hant"))
    record(page)
    page.click("#card-redo")
    expect(page.locator("#card-record")).to_have_class(re.compile(r"\brecording\b"))
    page.wait_for_timeout(TAKE_S * 1000)
    page.click("#card-record")
    expect(page.locator("#card-next")).to_be_enabled(timeout=10_000)
    page.click("#card-next")
    for n in (5, 6):
        expect(page.locator("#card-progress")).to_have_text(f"{n} of 6")
        shown.append(card_face(page, TRADITIONAL, "zh-Hant"))
        record(page)
        page.click("#card-next")

    # Every card was shown, the g01 error card (睡覺 / 睡觉 in its note) among them (R88).
    assert "一杯睡" in shown, shown

    # R90: nothing has been shared or downloaded yet, so the delete confirm says so.
    expect(page.locator("#screen-done")).to_be_visible()
    assert delete_confirm_text(page) == copy_text("done.delete_confirm_unsent")
    bundle, code = download_bundle(page, tmp)
    # A download can't be confirmed, so the session stays (done screen, same code). The store
    # remembers that it was downloaded, so the delete confirm no longer says nothing was sent.
    page.wait_for_function(
        f"async () => (await ({STORED_SESSION.strip()})()).downloaded === true"
    )
    page.reload()
    expect(page.locator("#screen-done")).to_be_visible()
    expect(page.locator("#done-code")).to_have_text(code)
    assert delete_confirm_text(page) == copy_text("done.delete_confirm")
    page_clean(page, problems)

    # R77: the share sheet's "success" deletes nothing; the button offers to send again.
    context.add_init_script(FAKE_SHARE)
    page.reload()
    share = page.locator("#share-button")
    expect(share).to_be_enabled(timeout=10_000)
    expect(share).to_have_text(copy_text("share.button"))
    assert stored_session(page)["shared"] is False
    share.click()
    expect(page.locator("#share-status")).to_have_text(copy_text("share.done"))
    expect(share).to_have_text(copy_text("share.again"))
    # The page never claims a state the store doesn't hold: "Send again" is already saved.
    assert stored_session(page)["shared"] is True
    again = [
        c
        for c in page.evaluate("window.__shareTextChanges")
        if c["text"] == copy_text("share.again")
    ]
    # No save may still be in flight when the page says "Send again".
    assert again and all(c["writes"] == 0 for c in again), again
    shared = page.evaluate("window.__shared")
    assert shared == {
        "name": bundle.name,
        "type": "application/zip",
        "size": bundle.stat().st_size,
    }, shared
    page.wait_for_function(
        "() => !document.getElementById('share-button').dataset.busy"
    )
    page.reload()
    expect(page.locator("#screen-done")).to_be_visible()
    expect(page.locator("#done-code")).to_have_text(code)
    expect(share).to_have_text(copy_text("share.again"))
    expect(share).to_be_enabled(timeout=10_000)
    share.click()
    page.wait_for_function("() => window.__shares === 1")
    assert page.evaluate("window.__shared.size") == bundle.stat().st_size

    # "Delete from this phone": cancelling the confirm keeps everything; accepting removes it.
    dialogs: list[str] = []
    page.once("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.click("#done-delete")
    expect(share).to_be_visible()
    expect(page.locator('[data-copy="done.body"]')).to_be_visible()
    page.once("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    page.click("#done-delete")
    expect(page.locator("#share-status")).to_have_text(copy_text("done.deleted"))
    expect(share).to_be_hidden()
    expect(page.locator("#done-delete")).to_be_hidden()
    # "Now send the recordings" is moot once they are gone.
    expect(page.locator('[data-copy="done.body"]')).to_be_hidden()
    assert dialogs == [copy_text("done.delete_confirm")] * 2, dialogs
    page_clean(page, problems)
    page.reload()
    expect(page.locator("#screen-welcome")).to_be_visible()
    context.close()
    return bundle, shown


def finish_early(browser, base: str, tmp: Path, problems: list[str]) -> Path:
    """One card in simplified characters, then "finish and send what I have", on a microphone
    that reports settings the way iOS Safari does."""
    context = new_context(
        browser, base, problems, before=(SAFARI_SETTINGS,), accept_downloads=True
    )
    page = context.new_page()
    watch(page, problems)
    start_session(page, base)
    page.click("#background-next")  # the defaults: simplified, characters only
    check_microphone(page)
    expect(page.locator("#card-progress")).to_have_text("1 of 6")
    expect(page.locator("#card-pinyin")).to_be_hidden()
    card_face(page, SIMPLIFIED, "zh-Hans")
    record(page)
    finish = page.locator("#card-finish")
    expect(finish).to_have_text(copy_text("card.finish_early"))
    dialogs: list[str] = []
    page.once("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    finish.click()
    expect(page.locator("#card-progress")).to_have_text("1 of 6")
    page.once("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    finish.click()
    assert dialogs == [copy_text("card.finish_early_confirm")] * 2, dialogs
    # R90: before anything is sent the delete confirm says so; once the file was downloaded, not.
    expect(page.locator("#screen-done")).to_be_visible()
    assert delete_confirm_text(page) == copy_text("done.delete_confirm_unsent")
    bundle, _ = download_bundle(page, tmp)
    assert delete_confirm_text(page) == copy_text("done.delete_confirm")
    page_clean(page, problems)
    context.close()
    with zipfile.ZipFile(bundle) as z:
        session = json.loads(z.read("session.json"))
    if (len(session["clips"]), len(session["skipped"])) != (1, 5):
        problems.append(
            f"finish early: {len(session['clips'])} clips, {len(session['skipped'])} skipped"
        )
    if session["speaker"]["script"] != "simplified":
        problems.append(f"finish early: script {session['speaker']['script']}")
    safari = {
        "echoCancellation": False,
        "noiseSuppression": None,
        "autoGainControl": None,
    }
    if session["device"]["constraints"] != safari:
        problems.append(f"finish early: constraints {session['device']['constraints']}")
    return bundle


def blocked_microphone(browser, base: str, problems: list[str]) -> None:
    """A refused microphone shows the how-to-allow message and lets the volunteer try again."""
    refuse = (
        "navigator.mediaDevices.getUserMedia = async () => {"
        " throw new DOMException('denied', 'NotAllowedError'); };"
    )
    context = new_context(browser, base, problems, before=(refuse,))
    page = context.new_page()
    watch(page, problems)
    start_session(page, base)
    page.click("#background-next")
    page.click("#mic-allow")
    expect(page.locator("#mic-error")).to_be_visible()
    expect(page.locator("#mic-error")).to_have_text(copy_text("error.mic_blocked"))
    expect(page.locator("#mic-allow")).to_be_enabled()
    page_clean(page, problems)
    context.close()


def in_app_browser(browser, base: str, problems: list[str]) -> None:
    """R84: WeChat's webview gets "open this in Safari" and nothing else."""
    context = new_context(browser, base, problems, user_agent=WECHAT_UA)
    page = context.new_page()
    watch(page, problems)
    page.goto(base + STANDIN)
    expect(page.locator("#screen-error")).to_be_visible()
    expect(page.locator("#error-text")).to_have_text(copy_text("error.in_app_browser"))
    expect(page.locator("#error-detail")).to_be_empty()
    for hidden in ("#screen-welcome", "#dev-banner", "#error-banner"):
        expect(page.locator(hidden)).to_be_hidden()
    page_clean(page, problems)
    # The text-field check must see one when there is one (a probe, after the page's own check).
    page.evaluate(
        "document.body.append(Object.assign(document.createElement('textarea'), {id: 'probe'}))"
    )
    try:
        page.wait_for_function("window.__textFields.length === 1", timeout=2000)
    except PlaywrightTimeout:
        problems.append("the text-field check did not see a probe textarea")
    context.close()


def declined(browser, base: str, problems: list[str]) -> None:
    """From the site root (its redirect runs under its own CSP): "No thanks" ends politely and
    keeps nothing."""
    context = new_context(browser, base, problems)
    page = context.new_page()
    watch(page, problems)
    page.goto(base.removesuffix("app/") + STANDIN)
    expect(page).to_have_url(base + STANDIN)
    page.click("#welcome-start")
    page.click("#consent-decline")
    expect(page.locator("#screen-declined")).to_be_visible()
    expect(page.locator("#screen-declined")).to_have_text(copy_text("consent.declined"))
    page_clean(page, problems)
    page.reload()
    expect(page.locator("#screen-welcome")).to_be_visible()
    context.close()


def volunteer_mode(browser, base: str, site: Path, problems: list[str]) -> None:
    """Without ?dev=1 the kit runs only on the real consent text and an approved deck."""
    context = new_context(browser, base, problems)
    page = context.new_page()
    watch(page, problems)
    page.goto(base)
    deck = site / "deck" / "s05-v1.json"
    ready = (
        (site / "CONSENT.md").exists()
        and deck.exists()
        and any(
            c.get("status") == "approved" for c in json.loads(deck.read_text())["card"]
        )
    )
    expect(
        page.locator("#screen-welcome" if ready else "#screen-error")
    ).to_be_visible()
    expect(page.locator("#dev-banner")).to_be_hidden()
    page_clean(page, problems)
    context.close()


def copy_text(key: str) -> str:
    """A string as the kit shows it: kit/copy.json when merged, else the stand-in."""
    for path in (KIT / "copy.json", KIT / "app" / "standin" / "copy.json"):
        if path.exists():
            data = json.loads(path.read_text())
            value = data.get(key)
            if value is None:  # nested form
                value = functools.reduce(
                    lambda node, part: (
                        (node or {}).get(part) if isinstance(node, dict) else None
                    ),
                    key.split("."),
                    data,
                )
            if isinstance(value, str):
                return value
    raise KeyError(key)


def run(tmp: Path) -> tuple[list[Path], list[str], list[str]]:
    site = tmp / "site"
    subprocess.run(
        [str(KIT / "assemble-site.sh"), str(site)], check=True, capture_output=True
    )
    mic = tmp / "fake-mic.wav"
    write_fake_mic(mic)
    server = serve(site)
    base = f"http://127.0.0.1:{server.server_address[1]}/app/"
    problems: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=[
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-audio-capture={mic}",
                ]
            )
            bundle, shown = volunteer_session(browser, base, tmp, problems)
            early = finish_early(browser, base, tmp, problems)
            blocked_microphone(browser, base, problems)
            in_app_browser(browser, base, problems)
            declined(browser, base, problems)
            volunteer_mode(browser, base, site, problems)
            browser.close()
    finally:
        server.shutdown()
    return [bundle, early], shown, problems


def check_fidelity(bundle: Path, shown: list[str]) -> list[str]:
    problems = []
    with zipfile.ZipFile(bundle) as z:
        session = json.loads(z.read("session.json"))
        clips = {c["card"]: z.read(c["file"]) for c in session["clips"]}
    print(f"  device: {json.dumps(session['device'])}")
    expect_speaker = {
        "background": "heritage",
        "grew_up_hearing": "taiwan",
        "reading": "hanzi+pinyin",
        "script": "traditional",
    }
    if session["speaker"] != expect_speaker:
        problems.append(f"speaker {session['speaker']}")
    if len(session["clips"]) != 5 or len(session["skipped"]) != 1:
        problems.append(
            f"{len(session['clips'])} clips, {len(session['skipped'])} skipped"
        )
    takes = [c["takes"] for c in session["clips"]]
    if takes != [1, 1, 2, 1, 1]:
        problems.append(f"takes {takes}")
    constraints = session["device"]["constraints"]
    if constraints != {
        "echoCancellation": False,
        "noiseSuppression": False,
        "autoGainControl": False,
    }:
        problems.append(f"constraints {constraints}")
    if session["consent"]["version"] not in {"standin"} and not re.fullmatch(
        r"v\d+(?:\.\d+)*", session["consent"]["version"]
    ):
        problems.append(f"consent version {session['consent']['version']}")
    # The gate pairs' twins are never read back to back.
    for twin in TWINS:
        at = [i for i, text in enumerate(shown) if text in twin]
        if at and (len(at) != 2 or at[1] - at[0] < 2):
            problems.append(f"twins {sorted(twin)} adjacent in {shown}")
    reference = speech_loop()
    for card, data in clips.items():
        with wave.open(io.BytesIO(data)) as w:
            x = (
                np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(
                    np.float64
                )
                / 32768
            )
        r = best_correlation(x, reference)
        print(f"  {card}: {len(x) / 16000:.2f} s, correlation with the fixture {r:.3f}")
        if r < MIN_CORRELATION:
            problems.append(
                f"{card}: correlation {r:.3f} < {MIN_CORRELATION} (pitch, speed or content wrong)"
            )
    return problems


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tonekit-kit-e2e-") as tmp:
        bundles, shown, problems = run(Path(tmp))
        print(f"cards shown: {' '.join(shown)}")
        deck = KIT / "app" / "standin" / "deck.json"
        for bundle in bundles:
            checked = subprocess.run(
                [
                    sys.executable,
                    str(KIT / "tests" / "check_bundle.py"),
                    str(bundle),
                    "--deck",
                    str(deck),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            sys.stdout.write(checked.stdout)
            sys.stderr.write(checked.stderr)
            if checked.returncode:
                problems.append(f"check_bundle.py failed on {bundle.name}")
        problems += check_fidelity(bundles[0], shown)
    for p in problems:
        print(f"FAIL {p}", file=sys.stderr)
    print("e2e: OK" if not problems else f"e2e: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
