#!/usr/bin/env python3
"""The kit end to end in headless Chromium, with the shared fixture as the microphone.

Assembles the site as Pages does, serves it locally, and walks a volunteer's session in dev mode
on the stand-in deck: consent, background, microphone check, four cards (three recorded about
1.5 s each, one skipped), with a reload in the middle that must resume where it left off. Then
it downloads the bundle (headless Chromium has no share sheet) and checks it: the contract
(check_bundle.py) and fidelity (every clip is the fixture's speech, at the right pitch and speed).

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

import numpy as np
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
    """Page errors, console errors and failed requests (other than optional content) are problems."""
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


# Stands in for the iOS share sheet: records what it was given, then succeeds.
FAKE_SHARE = """
navigator.canShare = (data) => Boolean(data && data.files && data.files.length);
navigator.share = async (data) => {
  const f = data.files[0];
  window.__shared = {name: f.name, type: f.type, size: f.size};
};
"""

# Simulates the screen locking / switching apps: the page becomes hidden.
HIDE_PAGE = """
Object.defineProperty(document, "hidden", {value: true, configurable: true});
document.dispatchEvent(new Event("visibilitychange"));
Object.defineProperty(document, "hidden", {value: false, configurable: true});
"""


def volunteer_session(
    browser, base: str, tmp: Path, problems: list[str]
) -> tuple[Path, list[str]]:
    """The whole flow on the stand-in deck; returns the downloaded bundle and the cards shown."""
    shown: list[str] = []
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    watch(page, problems)

    page.goto(base + "?dev=1&deck=standin")
    expect(page.locator("#dev-banner")).to_be_visible()
    page.click("#welcome-start")

    expect(page.locator("#screen-consent")).to_be_visible()
    expect(page.locator("#consent-text h2").first).to_be_visible()
    page.click("#consent-agree")

    expect(page.locator("#screen-background")).to_be_visible()
    for question, value in (
        ("background", "prefer_not"),
        ("grew_up_hearing", "prefer_not"),
        ("reading", "hanzi"),
    ):
        expect(page.locator(f'#q-{question} [data-value="{value}"]')).to_have_attribute(
            "aria-checked", "true"
        )
    page.click('#q-background [data-value="heritage"]')
    page.click('#q-grew_up_hearing [data-value="taiwan"]')
    page.click('#q-reading [data-value="hanzi+pinyin"]')
    page.click("#background-next")

    expect(page.locator("#screen-mic")).to_be_visible()
    page.click("#mic-allow")
    expect(page.locator("#mic-continue")).to_be_visible(timeout=10_000)
    expect(page.locator("#mic-status")).not_to_be_empty()
    page.click("#mic-continue")

    # Card 1, then close-and-reopen: the session resumes on the same card, take kept.
    expect(page.locator("#card-progress")).to_have_text("1 of 4")
    expect(page.locator("#card-pinyin")).to_be_visible()
    shown.append(page.locator("#card-text").inner_text())
    record(page)
    page.reload()
    expect(page.locator("#screen-pause")).to_be_visible()
    page.click("#pause-resume")
    expect(page.locator("#card-progress")).to_have_text("1 of 4")
    expect(page.locator("#card-play")).to_be_visible()
    assert page.locator("#card-text").inner_text() == shown[0]
    page.click("#card-next")

    # Card 2: the page is hidden mid-take (screen locked): the take is dropped, the kit pauses,
    # and after resuming the card is recorded again.
    expect(page.locator("#card-progress")).to_have_text("2 of 4")
    shown.append(page.locator("#card-text").inner_text())
    page.click("#card-record")
    page.wait_for_timeout(500)
    page.evaluate(HIDE_PAGE)
    expect(page.locator("#screen-pause")).to_be_visible()
    page.click("#pause-resume")
    expect(page.locator("#card-progress")).to_have_text("2 of 4")
    expect(page.locator("#card-next")).to_be_disabled()
    expect(page.locator("#card-record")).not_to_have_class(re.compile(r"\brecording\b"))
    record(page)
    page.click("#card-next")

    # Card 3: skipped. Card 4: recorded, then redone.
    expect(page.locator("#card-progress")).to_have_text("3 of 4")
    shown.append(page.locator("#card-text").inner_text())
    page.click("#card-skip")
    page.click("#card-next")
    expect(page.locator("#card-progress")).to_have_text("4 of 4")
    shown.append(page.locator("#card-text").inner_text())
    record(page)
    page.click("#card-redo")
    expect(page.locator("#card-record")).to_have_class(re.compile(r"\brecording\b"))
    page.wait_for_timeout(TAKE_S * 1000)
    page.click("#card-record")
    expect(page.locator("#card-next")).to_be_enabled(timeout=10_000)
    page.click("#card-next")

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

    # A download can't be confirmed, so the session stays (done screen, same code)...
    page.reload()
    expect(page.locator("#screen-done")).to_be_visible()
    expect(page.locator("#done-code")).to_have_text(code)
    # ... until the share sheet takes it: then the phone keeps nothing.
    context.add_init_script(FAKE_SHARE)
    page.reload()
    expect(page.locator("#share-button")).to_be_enabled(timeout=10_000)
    page.click("#share-button")
    expect(page.locator("#share-status")).not_to_be_empty()
    shared = page.evaluate("window.__shared")
    assert shared == {
        "name": bundle.name,
        "type": "application/zip",
        "size": bundle.stat().st_size,
    }, shared
    page.reload()
    expect(page.locator("#screen-welcome")).to_be_visible()
    context.close()
    return bundle, shown


def blocked_microphone(browser, base: str, problems: list[str]) -> None:
    """A refused microphone shows the how-to-allow message and lets the volunteer try again."""
    context = browser.new_context()
    context.add_init_script(
        "navigator.mediaDevices.getUserMedia = async () => {"
        " throw new DOMException('denied', 'NotAllowedError'); };"
    )
    page = context.new_page()
    watch(page, problems)
    page.goto(base + "?dev=1&deck=standin")
    page.click("#welcome-start")
    page.click("#consent-agree")
    page.click("#background-next")
    page.click("#mic-allow")
    expect(page.locator("#mic-error")).to_be_visible()
    expect(page.locator("#mic-error")).to_have_text(copy_text("error.mic_blocked"))
    expect(page.locator("#mic-allow")).to_be_enabled()
    context.close()


def volunteer_mode(browser, base: str, site: Path, problems: list[str]) -> None:
    """Without ?dev=1 the kit runs only on the real consent text and an approved deck."""
    context = browser.new_context()
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
    context.close()


def copy_text(key: str) -> str:
    """A string as the kit shows it: kit/copy.json when merged, else the stand-in."""
    for path in (KIT / "copy.json", KIT / "app" / "standin" / "copy.json"):
        if path.exists():
            data = json.loads(path.read_text())
            value = data.get(key)
            if value is None:  # nested form
                value = functools.reduce(
                    lambda node, part: (node or {}).get(part), key.split("."), data
                )
            if isinstance(value, str):
                return value
    raise KeyError(key)


def run(tmp: Path) -> tuple[Path, list[str], list[str]]:
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
            blocked_microphone(browser, base, problems)
            volunteer_mode(browser, base, site, problems)
            browser.close()
    finally:
        server.shutdown()
    return bundle, shown, problems


def check_fidelity(bundle: Path, shown: list[str]) -> list[str]:
    problems = []
    with zipfile.ZipFile(bundle) as z:
        session = json.loads(z.read("session.json"))
        clips = {c["card"]: z.read(c["file"]) for c in session["clips"]}
    expect_speaker = {
        "background": "heritage",
        "grew_up_hearing": "taiwan",
        "reading": "hanzi+pinyin",
    }
    if session["speaker"] != expect_speaker:
        problems.append(f"speaker {session['speaker']}")
    if len(session["clips"]) != 3 or len(session["skipped"]) != 1:
        problems.append(
            f"{len(session['clips'])} clips, {len(session['skipped'])} skipped"
        )
    takes = [c["takes"] for c in session["clips"]]
    if takes != [1, 1, 2]:
        problems.append(f"takes {takes}")
    constraints = session["device"]["constraints"]
    if constraints != {
        "echoCancellation": False,
        "noiseSuppression": False,
        "autoGainControl": False,
    }:
        problems.append(f"constraints {constraints}")
    if session["consent"]["version"] not in {"standin"} and not re.fullmatch(
        r"v\d+", session["consent"]["version"]
    ):
        problems.append(f"consent version {session['consent']['version']}")
    # The gate pair's twins (一杯水 / 一杯睡) are never read back to back.
    twins = [i for i, text in enumerate(shown) if text in {"一杯水", "一杯睡"}]
    if len(twins) != 2 or twins[1] - twins[0] < 2:
        problems.append(f"twins adjacent in {shown}")
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
        bundle, shown, problems = run(Path(tmp))
        print(f"cards shown: {' '.join(shown)}")
        checked = subprocess.run(
            [sys.executable, str(KIT / "tests" / "check_bundle.py"), str(bundle)],
            capture_output=True,
            text=True,
        )
        sys.stdout.write(checked.stdout)
        sys.stderr.write(checked.stderr)
        if checked.returncode:
            problems.append("check_bundle.py failed")
        problems += check_fidelity(bundle, shown)
    for p in problems:
        print(f"FAIL {p}", file=sys.stderr)
    print("e2e: OK" if not problems else f"e2e: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
