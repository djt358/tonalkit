"""The data root, corpus registry and purge log (contracts.md sections 3 and 6). Volunteer audio
and speaker metadata live under the data root (`$TONEKIT_DATA`), never in the repository. This
module loads and checks the formats; selection and refusals are the registry's job
(`tonekit_harness.registry`), writing is intake's and purge's."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from textwrap import indent
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, ValidationError, ValidationInfo, model_validator

from .base import StrictModel, format_validation_error
from .bundle import SESSION_ALPHABET, SESSION_CODE_PATTERN
from .enums import Background, GrewUpHearing
from .lects import LectError, lect_rules
from .pack import PackInfo, load_pack_info
from .relpath import is_relative_inside

DATA_ENV = "TONEKIT_DATA"
DEFAULT_DATA_DIRNAME = "tonekit-data"

Kind = Literal["recorded", "public", "synthetic"]
Split = Literal["gate", "dev", "calib", "heldout"]

SessionCode = Annotated[str, Field(pattern=SESSION_CODE_PATTERN)]
_VOLUNTEER_ID = re.compile(r"v-([a-hj-np-z2-9]{6})")


class RegistryError(ValueError):
    """A registry file could not be read; the message starts with its path."""


# ---- where things are ---------------------------------------------------------------------


def data_root(cli_value: str | Path | None = None, *, environ: Mapping[str, str] | None = None) -> Path:
    """The data root: `tkh --data PATH`, else `$TONEKIT_DATA`, else `~/tonekit-data`. Absolute; it
    is not created."""
    env = (os.environ if environ is None else environ).get(DATA_ENV, "").strip()
    chosen = Path(cli_value) if cli_value is not None else Path(env) if env else Path.home() / DEFAULT_DATA_DIRNAME
    return chosen.expanduser().absolute()


def corpus_dir(root: Path, corpus_id: str) -> Path:
    return root / "corpora" / corpus_id


def corpus_file_path(root: Path, corpus_id: str) -> Path:
    return corpus_dir(root, corpus_id) / "corpus.toml"


def inbox_dir(root: Path) -> Path:
    return root / "inbox"


def purge_log_path(root: Path) -> Path:
    return root / "purge-log.jsonl"


# ---- speakers and corpora -----------------------------------------------------------------


class Speaker(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # v-<session code> for volunteers
    background: Background | None = None  # public corpora do not say
    grew_up_hearing: GrewUpHearing | None = None
    # The pack accent id this speaker is graded against; None means `speaker_accent`'s default (R82).
    accent: str | None = Field(default=None, min_length=1)
    split: Split
    sessions: list[SessionCode] = []

    @model_validator(mode="after")
    def _volunteer_id_names_its_session(self) -> Speaker:
        m = _VOLUNTEER_ID.fullmatch(self.id)
        if m and self.sessions != [m.group(1).upper()]:
            raise ValueError(
                f"speaker {self.id!r}: a volunteer id v-<code> needs sessions "
                f"[{m.group(1).upper()!r}], not {self.sessions}"
            )
        return self


class CorpusMeta(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    source: str = Field(min_length=1)  # a data-register.csv id
    kind: Kind
    lect: str = Field(min_length=1)
    manifest: str = "manifest.jsonl"  # relative to the corpus directory

    @model_validator(mode="after")
    def _manifest_stays_in_the_corpus_directory(self) -> CorpusMeta:
        if not is_relative_inside(self.manifest):
            raise ValueError(f"manifest {self.manifest!r} must be a relative path inside the corpus directory")
        return self


class CorpusFile(StrictModel):
    corpus: CorpusMeta
    speaker: list[Speaker] = []

    @model_validator(mode="after")
    def _rules(self, info: ValidationInfo) -> CorpusFile:
        # The accents are the pack's: pass it as validation context (`parse_corpus` does); without,
        # the default pack (packs/cmn/cmn.toml) stands in.
        pack = (info.context or {}).get("pack") or load_pack_info(None)
        problems = _unique_problems(self) + _split_problems(self) + _accent_problems(self, pack)
        if problems:
            raise ValueError("\n".join(problems))
        return self


def _unique_problems(corpus: CorpusFile) -> list[str]:
    ids = Counter(s.id for s in corpus.speaker)
    sessions = Counter(code for s in corpus.speaker for code in s.sessions)
    return [f"speaker {i!r} appears more than once" for i, n in ids.items() if n > 1] + [
        f"session {c!r} belongs to more than one speaker" for c, n in sessions.items() if n > 1
    ]


def _split_problems(corpus: CorpusFile) -> list[str]:
    """Public and synthetic corpora store the hash split: a hand-edited corpus.toml must not put a
    held-out speaker into fitting. Recorded corpora can move speakers between splits (R82)."""
    kind = corpus.corpus.kind
    if kind == "recorded":
        return []
    return [
        f"speaker {s.id!r}: split {s.split!r} but a {kind} corpus stores the hash split {hashed_split(s.id)!r}"
        for s in corpus.speaker
        if s.split != hashed_split(s.id)
    ]


def _accent_problems(corpus: CorpusFile, pack: PackInfo) -> list[str]:
    lect = corpus.corpus.lect
    if lect != pack.lect:
        return [f"corpus lect {lect!r} but the pack is for {pack.lect!r}"]
    known = ", ".join(sorted(pack.accent_ids))
    problems = []
    for s in corpus.speaker:
        try:
            accent = speaker_accent(s, lect)
        except LectError as e:
            problems.append(f"speaker {s.id!r}: {e}")
            continue
        if accent not in pack.accent_ids:
            what = "accent" if s.accent else "default accent"
            problems.append(f"speaker {s.id!r}: {what} {accent!r} is not an accent of the pack (known: {known})")
    return problems


def parse_corpus(data: dict, *, pack: str | Path | PackInfo | None = None, source: str = "corpus") -> CorpusFile:
    """Validate a corpus file's data (its TOML as a dict) against the contract and the accents of
    `pack` (a pack TOML path; default packs/cmn/cmn.toml). Raises `RegistryError` listing every problem."""
    info = pack if isinstance(pack, PackInfo) else load_pack_info(pack)
    try:
        return CorpusFile.model_validate(data, context={"pack": info})
    except ValidationError as e:
        problems = format_validation_error(e, data, {"speaker": "id"})
        raise RegistryError(f"{source}: invalid corpus file\n{indent(problems, '  ')}") from e


def load_corpus_file(path: str | Path, *, pack: str | Path | PackInfo | None = None) -> CorpusFile:
    """Read and validate a `corpus.toml` (see `parse_corpus`). Raises `RegistryError` listing every problem."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise RegistryError(f"{path}: invalid TOML: {e}") from e
    return parse_corpus(data, pack=pack, source=str(path))


# ---- format rules: ids, accents, splits ---------------------------------------------------


def volunteer_speaker_id(session_code: str) -> str:
    """`v-<session code>` in lower case, the speaker id of a volunteer's session."""
    if not re.fullmatch(SESSION_CODE_PATTERN, session_code):
        raise ValueError(f"{session_code!r} is not a session code (six characters of {SESSION_ALPHABET})")
    return f"v-{session_code.lower()}"


def default_accent(grew_up_hearing: str | None, lect: str = "cmn") -> str:
    """The pack accent a speaker is graded against when none is stated, from where they grew up
    hearing the lect (cmn: `taiwan` is cmn-TW, everything else, or unknown, cmn-standard)."""
    return lect_rules(lect).default_accent(grew_up_hearing)


def speaker_accent(speaker: Speaker, lect: str = "cmn") -> str:
    """The pack accent id a speaker is graded against: their own `accent`, else the default for
    where they grew up hearing the lect (R82). The CLI's `--accent` overrides both."""
    return speaker.accent or default_accent(speaker.grew_up_hearing, lect)


def hashed_split(speaker_id: str) -> Split:
    """The split of a public-corpus speaker: sha256 of the id (its first 8 bytes, big-endian,
    modulo 100) puts 60% in `calib`, 20% in `dev`, 20% in `heldout`. Stable forever: a change would
    move speakers between the fitting and the held-out sets."""
    bucket = int.from_bytes(hashlib.sha256(speaker_id.encode("utf-8")).digest()[:8], "big") % 100
    if bucket < 60:
        return "calib"
    return "dev" if bucket < 80 else "heldout"


def default_split(kind: Kind, speaker_id: str) -> Split:
    """Recorded speakers (volunteers, DJ) default to `gate`; other corpora split by hash."""
    return "gate" if kind == "recorded" else hashed_split(speaker_id)


# ---- the purge log ------------------------------------------------------------------------


class PurgeRecord(StrictModel):
    """One line of purge-log.jsonl: what `tkh purge --session CODE` did."""

    session: SessionCode
    purged_at: AwareDatetime
    files_removed: int = Field(ge=0)  # a count: file names would say who the speaker was
    corpora: list[str]


def load_purge_log(path: str | Path) -> list[PurgeRecord]:
    """The records of a purge log, oldest first; no file means no purges."""
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            where = f"{path}:{lineno}"
            try:
                records.append(PurgeRecord.model_validate(json.loads(line)))
            except json.JSONDecodeError as e:
                raise RegistryError(f"{where}: invalid JSON: {e}") from e
            except ValidationError as e:
                raise RegistryError(f"{where}: {format_validation_error(e)}") from e
    return records
