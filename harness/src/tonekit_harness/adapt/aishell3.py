"""AISHELL-3 (openslr.org/93, register id `aishell-3`): 218 native Mandarin speakers reading
scripted sentences, 44.1 kHz 16-bit mono WAV recorded about 20 cm from a high-fidelity
microphone. The pinyin was "manually transcribed from speech after recording, reflecting the actual
readings" (the corpus paper, Interspeech 2021): it is per recording and should give the spoken
tones, sandhi included (ruling R122).

The layout of `data_aishell3/` (as the lhotse recipe reads it):

    spk-info.txt                      speaker, age group, gender, accent (north / south / others);
                                      lines starting with # are comments
    train/content.txt, test/content.txt
                                      <utterance>.wav<TAB>广 guang3 州 zhou1 ...: hanzi and numbered
                                      pinyin alternating
    train/wav/<speaker>/<utterance>.wav, test/wav/...
                                      the speaker id is the utterance id's first 7 characters

The corpus's own train/test split is not used: speakers are split by hash (R69)."""

from __future__ import annotations

from pathlib import Path

from ..manifest import Condition
from . import drops
from .corpus_files import AdaptError, Found, SpeakerInfo, Utterance, read_text, require_dir
from .reading import Transcript

NAME = "aishell3"
SOURCE = "aishell-3"  # data-register.csv
CONDITION = Condition(noise="quiet", distance="20cm")
PARTS = ("train", "test")
SPEAKER_ID_LENGTH = 7
MAINLAND_ACCENTS = frozenset({"north", "south"})  # regions of mainland China


def read_corpus(src: Path) -> Found:
    """Every utterance the corpus's transcripts list, and its speakers' metadata."""
    hint = f" (pass the data_aishell3 directory: {src / 'data_aishell3'})" if (src / "data_aishell3").is_dir() else ""
    if not (src / "spk-info.txt").is_file():
        raise AdaptError(f"{src} has no spk-info.txt: expected the extracted data_aishell3 directory{hint}")
    parts = [p for p in PARTS if (src / p / "content.txt").is_file()]
    if not parts:
        raise AdaptError(f"{src} has neither train/content.txt nor test/content.txt{hint}")
    found = Found(speakers=_speakers(src / "spk-info.txt"))
    seen: set[str] = set()
    for part in parts:
        require_dir(src / part / "wav", f"the {part} audio")
        for line in _lines(src / part / "content.txt"):
            utterance = _utterance(line, src / part / "wav")
            if utterance.id in seen:
                utterance = Utterance(utterance.id, utterance.speaker, None, None, drops.MALFORMED)
            seen.add(utterance.id)
            found.utterances.append(utterance)
    return found


def _lines(path: Path) -> list[str]:
    text = read_text(path)
    if text is None:
        raise AdaptError(f"{path} is not UTF-8 text")
    return [line for line in text.splitlines() if line.strip()]


def _speakers(path: Path) -> dict[str, SpeakerInfo]:
    """Every speaker of spk-info.txt is a native Mandarin speaker (the corpus says so); one with a
    northern or southern accent grew up hearing it in mainland China (ruling R124)."""
    out = {}
    for line in _lines(path):
        if line.lstrip().startswith("#"):
            continue
        fields = line.split()
        accent = fields[3].lower() if len(fields) > 3 else ""
        grew_up = "mainland" if accent in MAINLAND_ACCENTS else None
        out[fields[0]] = SpeakerInfo(background="native", grew_up_hearing=grew_up)
    return out


def _utterance(line: str, wav_dir: Path) -> Utterance:
    name, _, rest = line.strip().partition("\t") if "\t" in line else line.strip().partition(" ")
    uid = name.removesuffix(".wav")
    speaker = uid[:SPEAKER_ID_LENGTH]
    audio = wav_dir / speaker / f"{uid}.wav"
    tokens = rest.split()
    if not tokens or len(tokens) % 2:
        return Utterance(uid, speaker, audio if audio.is_file() else None, None, drops.MALFORMED)
    transcript = Transcript(
        hanzi=tuple(tokens[0::2]), pinyin=tuple(tokens[1::2]), words=None, per_recording=True
    )
    return Utterance(uid, speaker, audio if audio.is_file() else None, transcript)
