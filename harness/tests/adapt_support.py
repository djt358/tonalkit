"""Tiny downloads of AISHELL-3 and THCHS-30 in their own on-disk layouts, for the `tkh adapt` tests.
The transcripts are made up here and the audio is the synthetic voice of support.py saying each
utterance's tones (AISHELL-3's at 44.1 kHz, as the corpus records); no recording of anyone."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
from support import RATE, utterance

AISHELL_RATE = 44_100


def wav_bytes(tones: list[str], rate: int = RATE, seed: int = 0) -> bytes:
    """16-bit PCM WAV bytes of the synthetic voice saying `tones` at `rate`."""
    x = utterance(tones, seed)
    if rate != RATE:
        x = resample_poly(x.astype(np.float64), 441, 160)
    buf = io.BytesIO()
    wavfile.write(buf, rate, np.round(np.clip(x, -1.0, 1.0) * 32767).astype(np.int16))
    return buf.getvalue()


def _tones(pinyin: str) -> list[str]:
    """What the synthetic voice says for a transcript: its tone digits (erhua and odd tokens aside)."""
    return [t[-1] if t[-1:].isdigit() else "1" for t in pinyin.split()] or ["1"]


# ---- AISHELL-3 ---------------------------------------------------------------------------------

# speaker -> accent in spk-info.txt; SSB0005 hashes to heldout, SSB0011 and SSB0012 to calib
AISHELL_SPEAKERS = {"SSB0005": "north", "SSB0011": "south", "SSB0012": "others"}

# utterance -> (hanzi, pinyin) and what the adapter should make of it (None: kept)
AISHELL_UTTERANCES: dict[str, tuple[str, str, str | None]] = {
    "SSB00050001": ("你好", "ni2 hao3", None),
    "SSB00050002": ("一个人", "yi2 ge4 ren2", None),
    "SSB00050003": ("你好", "ni3 hao3", "third tones"),
    "SSB00050004": ("哪儿", "na3 er5", "erhua"),
    "SSB00110001": ("不是", "bu2 shi4", None),
    "SSB00110002": ("展览馆", "zhan2 lan2 guan3", "more than one native reading"),
    "SSB00110003": ("你好吗", "ni2 hao3", "malformed"),
    "SSB00110004": ("妈妈", "ma1 ma5", "no audio"),
    "SSB00120001": ("一下", "yi2 xia5", "before a neutral syllable"),
    "SSB00120002": ("他们都去北京", "ta1 men5 dou1 qu4 bei3 jing1", "longer than"),
    "SSB00120003": ("看看", "kan4 kan5", "audio not readable"),
    "SSB00120004": ("我们", "wo3 men5", None),
}


def aishell3_download(where: Path) -> Path:
    """`where/data_aishell3` with spk-info.txt, train/ and test/ (SSB0012 is a test speaker)."""
    root = where / "data_aishell3"
    info = ["# AISHELL-3 speaker info (synthetic)", "# speaker\tage\tgender\taccent"]
    info += [f"{spk}\tB\tfemale\t{accent}" for spk, accent in AISHELL_SPEAKERS.items()]
    root.mkdir(parents=True)
    (root / "spk-info.txt").write_text("\n".join(info) + "\n", encoding="utf-8")
    contents: dict[str, list[str]] = {"train": [], "test": []}
    for seed, (uid, (hanzi, pinyin, outcome)) in enumerate(AISHELL_UTTERANCES.items()):
        part = "test" if uid.startswith("SSB0012") else "train"
        tokens = [tok for pair in zip(hanzi, pinyin.split()) for tok in pair]
        if outcome == "malformed":
            tokens = tokens[:-1]  # a hanzi without its pinyin
        contents[part].append(f"{uid}.wav\t{' '.join(tokens)}")
        if outcome == "no audio":
            continue
        wav = root / part / "wav" / uid[:7] / f"{uid}.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        if outcome == "audio not readable":
            wav.write_bytes(b"RIFF\x00\x00not a wav")
        else:
            wav.write_bytes(wav_bytes(_tones(pinyin), AISHELL_RATE, seed))
    for part, lines in contents.items():
        (root / part / "content.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


# ---- THCHS-30 ----------------------------------------------------------------------------------

# A11 hashes to calib, B4 to dev, C4 to heldout
THCHS_UTTERANCES: dict[str, tuple[str, str, str, str | None]] = {
    # utterance -> (words, pinyin, phones, outcome)
    "A11_0": ("你好 世界", "ni2 hao3 shi4 jie4", "n i2 h ao3 sh ix4 j ie4", None),
    "A11_1": ("不对 你好", "bu4 dui4 ni3 hao3", "b u4 d ui4 n i3 h ao3", None),
    "A11_2": ("我 想 去", "wo3 xiang3 qu4", "uu uo3 x iang3 q v4", "word boundary"),
    "A11_3": ("一月", "yi1 yue4", "ii i1 vv ve4", "dictionary tone"),
    "B4_0": ("不是 我 老爹", "bu2 shi4 wo3 lao3 die1", "b u2 sh ix4 uu uo3 l ao3 d ie1", "mixed"),
    "B4_1": ("妈妈 骂 马", "ma1 ma5 ma4 ma3", "m a1 m a5 m a4 m a2", "malformed"),
    "B4_2": ("骂 马", "ma4 ma3", "m a4 m a3", "no transcript"),
    "C4_0": ("妈妈 骂 马", "ma1 ma5 ma4 ma3", "m a1 m a5 m a4 m a3", None),
}


def thchs30_download(where: Path) -> Path:
    """`where/data_thchs30` with data/*.wav.trn and the audio in train/ (A11, B4), dev/ (A11_3) and
    test/ (C4); train/ also holds the one-line .trn pointers into data/ that the download has."""
    root = where / "data_thchs30"
    (root / "data").mkdir(parents=True)
    for seed, (uid, (words, pinyin, phones, outcome)) in enumerate(THCHS_UTTERANCES.items()):
        part = "test" if uid.startswith("C") else "dev" if uid == "A11_3" else "train"
        (root / part).mkdir(exist_ok=True)
        (root / part / f"{uid}.wav").write_bytes(wav_bytes(_tones(pinyin), RATE, seed))
        if outcome == "no transcript":
            continue
        (root / "data" / f"{uid}.wav.trn").write_text(f"{words}\n{pinyin}\n{phones}\n", encoding="utf-8")
        (root / part / f"{uid}.wav.trn").write_text(f"../data/{uid}.wav.trn\n", encoding="utf-8")
    return root
