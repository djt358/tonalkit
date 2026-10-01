"""The session bundle the kit exports (contracts.md section 2): a zip of `session.json` and one
16 kHz mono 16-bit PCM WAV per recorded card. `read_bundle` checks the zip's layout and the WAV
headers; decoding and quality control of the audio is intake's job."""

from __future__ import annotations

import io
import json
import re
import wave
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from textwrap import indent
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from .base import StrictModel, format_validation_error
from .enums import Background, GrewUpHearing

# Six characters from this alphabet: A-Z and 2-9 without 0, O, 1 and I.
SESSION_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SESSION_CODE_PATTERN = r"^[A-HJ-NP-Z2-9]{6}$"
SESSION_FILE = "session.json"
CLIP_RATE, CLIP_CHANNELS, CLIP_SAMPLE_WIDTH = 16_000, 1, 2  # Hz, mono, 16-bit bytes

_CARD_ID = r"^[a-z0-9-]+$"
CardId = Annotated[str, Field(pattern=_CARD_ID)]
_CLIP_MEMBER = re.compile(r"clips/[a-z0-9-]+\.wav")


class BundleError(ValueError):
    """A bundle could not be read; the message starts with the zip's path."""


class DeckRef(StrictModel):
    id: str = Field(pattern=_CARD_ID)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")  # of the deck file the kit loaded


class Consent(StrictModel):
    version: str = Field(min_length=1)
    agreed_at: AwareDatetime


class SpeakerInfo(StrictModel):
    background: Background
    grew_up_hearing: GrewUpHearing
    reading: Literal["hanzi", "hanzi+pinyin"]


class DeviceConstraints(StrictModel):
    """What the browser reported (null if it did not say), not what the kit asked for."""

    echoCancellation: bool | None
    noiseSuppression: bool | None
    autoGainControl: bool | None


class Device(StrictModel):
    user_agent: str = Field(min_length=1)
    input_sample_rate: int = Field(gt=0)  # the actual input rate, before resampling to 16 kHz
    constraints: DeviceConstraints


class SessionClip(StrictModel):
    card: CardId
    file: str
    takes: int = Field(ge=1)
    duration_s: float = Field(gt=0)
    peak: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _file_is_named_after_the_card(self) -> SessionClip:
        if self.file != f"clips/{self.card}.wav":
            raise ValueError(f"clip {self.card!r}: file must be 'clips/{self.card}.wav', not {self.file!r}")
        return self


class Session(StrictModel):
    schema_: Literal["tonekit.session.v1"] = Field(alias="schema")
    deck: DeckRef
    # the only key for a deletion request
    session: str = Field(
        pattern=SESSION_CODE_PATTERN, description=f"six characters from {SESSION_ALPHABET}, random, made by the kit"
    )
    started_at: AwareDatetime
    finished_at: AwareDatetime
    consent: Consent
    speaker: SpeakerInfo
    device: Device
    clips: list[SessionClip]
    skipped: list[CardId] = []

    @model_validator(mode="after")
    def _consistent(self) -> Session:
        problems = []
        if self.finished_at < self.started_at:
            problems.append("finished_at is before started_at")
        recorded = [c.card for c in self.clips]
        problems += [f"card {c!r} is listed more than once" for c, n in Counter(recorded).items() if n > 1]
        problems += [f"card {c!r} is skipped more than once" for c, n in Counter(self.skipped).items() if n > 1]
        problems += [f"card {c!r} is both skipped and recorded" for c in dict.fromkeys(self.skipped) if c in recorded]
        if problems:
            raise ValueError("\n".join(problems))
        return self


@dataclass(frozen=True)
class WavHeader:
    sample_rate: int
    channels: int
    sample_width: int  # bytes per sample
    frames: int

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate


@dataclass(frozen=True)
class Bundle:
    path: Path
    session: Session
    audio: dict[str, WavHeader]  # by card id: the header of clips/<card>.wav

    def clip_bytes(self, card: str) -> bytes:
        """The WAV file of `card`, as it is in the zip."""
        if card not in self.audio:
            raise KeyError(f"no clip for card {card!r} in {self.path}")
        with zipfile.ZipFile(self.path) as z:
            return z.read(f"clips/{card}.wav")


def read_bundle(zip_path: str | Path) -> Bundle:
    """Read and validate a bundle zip. Raises `BundleError` listing every problem."""
    path = Path(zip_path)
    if not path.is_file():
        raise BundleError(f"{path}: does not exist")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise BundleError(f"{path}: not a zip file") from None
    with z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        if SESSION_FILE not in names:
            raise BundleError(f"{path}: no {SESSION_FILE}")
        session = _read_session(z, path)
        problems = _layout_problems(names, session)
        audio, wav_problems = _read_headers(z, names, session)
    problems += wav_problems
    if problems:
        joined = "\n".join(problems)
        raise BundleError(f"{path}: invalid bundle\n{indent(joined, '  ')}")
    return Bundle(path=path, session=session, audio=audio)


def _read_session(z: zipfile.ZipFile, path: Path) -> Session:
    try:
        data = json.loads(z.read(SESSION_FILE).decode("utf-8"))
    except UnicodeDecodeError:
        raise BundleError(f"{path}: {SESSION_FILE}: not UTF-8 text") from None
    except json.JSONDecodeError as e:
        raise BundleError(f"{path}: {SESSION_FILE}: invalid JSON: {e}") from None
    if not isinstance(data, dict):
        raise BundleError(f"{path}: {SESSION_FILE}: expected a JSON object, got {type(data).__name__}")
    try:
        return Session.model_validate(data)
    except ValidationError as e:
        problems = format_validation_error(e, data, {"clips": "card"})
        raise BundleError(f"{path}: {SESSION_FILE} is invalid\n{indent(problems, '  ')}") from None


def _layout_problems(names: list[str], session: Session) -> list[str]:
    problems = [f"{n} appears twice" for n, count in Counter(names).items() if count > 1]
    problems += [
        f"unexpected file {n!r}" for n in dict.fromkeys(names) if n != SESSION_FILE and not _CLIP_MEMBER.fullmatch(n)
    ]
    listed = [c.file for c in session.clips]
    problems += [f"{SESSION_FILE} lists {f} but the zip does not have it" for f in listed if f not in names]
    problems += [
        f"{n} is in the zip but not listed in {SESSION_FILE}"
        for n in dict.fromkeys(names)
        if _CLIP_MEMBER.fullmatch(n) and n not in listed
    ]
    return problems


def _read_headers(
    z: zipfile.ZipFile, names: list[str], session: Session
) -> tuple[dict[str, WavHeader], list[str]]:
    audio: dict[str, WavHeader] = {}
    problems = []
    for clip in session.clips:
        if names.count(clip.file) != 1:
            continue  # missing or repeated: already reported
        try:
            audio[clip.card] = _check_wav(z.read(clip.file))
        except ValueError as e:
            problems.append(f"{clip.file}: {e}")
    return audio, problems


def _check_wav(data: bytes) -> WavHeader:
    """The header of a 16 kHz mono 16-bit PCM WAV with all its audio, else ValueError."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            header = WavHeader(w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes())
            whole = len(w.readframes(header.frames)) == header.frames * header.channels * header.sample_width
    except (wave.Error, EOFError) as e:
        raise ValueError(f"not a PCM WAV ({e})") from None
    if (header.sample_rate, header.channels, header.sample_width) != (CLIP_RATE, CLIP_CHANNELS, CLIP_SAMPLE_WIDTH):
        s = "s" if header.channels != 1 else ""
        raise ValueError(
            f"is {header.sample_rate} Hz, {header.channels} channel{s}, {8 * header.sample_width}-bit; "
            "need 16000 Hz, 1 channel, 16-bit"
        )
    if header.frames == 0:
        raise ValueError("has no audio")
    if not whole:
        raise ValueError("truncated: the file ends before the audio the header promises")
    return header
