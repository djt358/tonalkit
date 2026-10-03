"""The session bundle the kit exports (contracts.md section 2): a zip of `session.json` and one
16 kHz mono 16-bit PCM WAV per recorded card. `read_bundle` checks the zip's layout and the WAV
headers; decoding and quality control of the audio is intake's job."""

from __future__ import annotations

import json
import lzma
import re
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from textwrap import indent
from typing import Literal

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from .base import StrictModel, format_validation_error
from .enums import Background, GrewUpHearing, Script
from .ids import CARD_ID_CHARS, CARD_ID_PATTERN, CardId
from .wav_check import WavHeader, check_wav

# Six characters from this alphabet: A-Z and 2-9 without 0, O, 1 and I.
SESSION_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SESSION_CODE_PATTERN = r"^[A-HJ-NP-Z2-9]{6}$"
SESSION_FILE = "session.json"

_CLIP_MEMBER = re.compile(rf"clips/{CARD_ID_CHARS}\.wav")


class BundleError(ValueError):
    """A bundle could not be read; the message starts with the zip's path."""


class DeckRef(StrictModel):
    id: str = Field(pattern=CARD_ID_PATTERN)  # the deck id
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")  # of the deck file the kit loaded


class Consent(StrictModel):
    version: str = Field(min_length=1)
    agreed_at: AwareDatetime


class SpeakerInfo(StrictModel):
    background: Background
    grew_up_hearing: GrewUpHearing
    reading: Literal["hanzi", "hanzi+pinyin"]
    script: Script  # the kit shows `text_traditional` where a card has one (R74)


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
    peak: float = Field(ge=0)  # no cap: intake QC flags clipping, the format only records it

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


# What reading a member of a damaged zip can raise: a bad CRC or header (BadZipFile), a broken or
# cut-off compressed stream (zlib.error for deflate, OSError for bz2, lzma.LZMAError for lzma,
# EOFError), and a compression method or encryption that zipfile cannot undo (NotImplementedError,
# RuntimeError).
_DAMAGE = (zipfile.BadZipFile, zlib.error, OSError, lzma.LZMAError, EOFError, NotImplementedError, RuntimeError)


def read_bundle(zip_path: str | Path) -> Bundle:
    """Read and validate a bundle zip. Raises `BundleError` listing every problem, including every
    member that is damaged (a bad CRC, a broken stream)."""
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
        members, damaged = _read_members(z, names)
    if SESSION_FILE not in members:
        raise _invalid(path, damaged)
    session = _parse_session(members[SESSION_FILE], path)
    audio, wav_problems = _read_headers(members, session)
    problems = _layout_problems(names, session) + damaged + wav_problems
    if problems:
        raise _invalid(path, problems)
    return Bundle(path=path, session=session, audio=audio)


def _invalid(path: Path, problems: list[str]) -> BundleError:
    joined = "\n".join(problems)
    return BundleError(f"{path}: invalid bundle\n{indent(joined, '  ')}")


def _read_members(z: zipfile.ZipFile, names: list[str]) -> tuple[dict[str, bytes], list[str]]:
    """The bytes of session.json and of every clip member that appears once, and a problem line for
    each of them that cannot be read. (A repeated clip name is a layout problem, not read.)"""
    counts = Counter(names)
    wanted = [SESSION_FILE] + [n for n in counts if _CLIP_MEMBER.fullmatch(n) and counts[n] == 1]
    members: dict[str, bytes] = {}
    problems = []
    for name in wanted:
        try:
            members[name] = z.read(name)
        except _DAMAGE as e:
            problems.append(f"{name}: damaged ({e})")
    return members, problems


def _parse_session(raw: bytes, path: Path) -> Session:
    try:
        data = json.loads(raw.decode("utf-8"))
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


def _read_headers(members: dict[str, bytes], session: Session) -> tuple[dict[str, WavHeader], list[str]]:
    audio: dict[str, WavHeader] = {}
    problems = []
    for clip in session.clips:
        data = members.get(clip.file)
        if data is None:
            continue  # missing, repeated or damaged: already reported
        try:
            audio[clip.card] = check_wav(data)
        except ValueError as e:
            problems.append(f"{clip.file}: {e}")
    return audio, problems
