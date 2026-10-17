"""THCHS-30 (openslr.org/18, register id `thchs-30`): 60 speakers, mostly college students fluent in
standard Mandarin, reading 1000 news sentences into one carbon microphone in an office; 16 kHz
16-bit mono WAV.

Its pinyin is written once per sentence of the script, not per recording: every speaker of a
sentence has the same transcript, and it mixes dictionary and sandhi tones (打好 da2 hao3 beside
把伞打开 ba3 san3 da3; 不 written bù before a fourth tone 336 times and bú 897 times). So it is read
as a script transcript (ruling R122), with the word boundaries of its first line.

The layout of `data_thchs30/` (as Kaldi's egs/thchs30 data preparation reads it):

    train/<utterance>.wav, dev/..., test/...   the audio; the speaker id is the utterance id up to
                                               its underscore (A11_0 is speaker A11)
    data/<utterance>.wav.trn                   three lines: the words (hanzi, separated by spaces),
                                               numbered pinyin per syllable, and phones (finals
                                               carry the tone digit)

The corpus's own train/dev/test split is not used: speakers are split by hash (R69)."""

from __future__ import annotations

from pathlib import Path

from ..manifest import Condition
from . import drops
from .corpus_files import AdaptError, Found, Utterance, read_text
from .reading import Transcript

NAME = "thchs30"
SOURCE = "thchs-30"  # data-register.csv
CONDITION = Condition(noise="office", distance="desk microphone")
PARTS = ("train", "dev", "test")


def read_corpus(src: Path) -> Found:
    """Every utterance with audio in train/, dev/ or test/, with its transcript from data/."""
    hint = f" (pass the data_thchs30 directory: {src / 'data_thchs30'})" if (src / "data_thchs30").is_dir() else ""
    parts = [src / p for p in PARTS if (src / p).is_dir()]
    if not parts or not (src / "data").is_dir():
        raise AdaptError(f"{src} needs data/ and train/, dev/ or test/: expected the data_thchs30 directory{hint}")
    found = Found()
    wavs = sorted((w for part in parts for w in part.glob("*.wav")), key=lambda w: w.name)
    for wav in wavs:
        uid = wav.name.removesuffix(".wav")
        speaker = uid.split("_", 1)[0]
        transcript, problem = _transcript(src / "data" / f"{wav.name}.trn")
        found.utterances.append(Utterance(uid, speaker, wav, transcript, problem))
    return found


def _transcript(path: Path) -> tuple[Transcript | None, str | None]:
    if not path.is_file():
        return None, drops.NO_TRANSCRIPT
    text = read_text(path)
    lines = [line.split() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return None, drops.MALFORMED
    words, pinyin = lines[0], lines[1]
    if len(lines) > 2 and _phone_tones(lines[2]) != [p[-1:] for p in pinyin]:
        return None, drops.MALFORMED  # the phone line gives other tones than the pinyin line
    hanzi = tuple(ch for word in words for ch in word)
    word_of = tuple(i for i, word in enumerate(words) for _ in word)
    return Transcript(hanzi=hanzi, pinyin=tuple(pinyin), words=word_of, per_recording=False), None


def _phone_tones(phones: list[str]) -> list[str]:
    """The tone digits of the phone line: each final ends in one, initials have none."""
    return [p[-1] for p in phones if p[-1:].isdigit()]
