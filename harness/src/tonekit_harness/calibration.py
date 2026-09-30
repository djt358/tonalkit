"""Which calibration a command grades with, and how a report says what it used.

The tonekit CLI reads `--calib`, else the `<pack stem>.calib.json` beside the pack if that file
exists (`load_pack` in crates/tonekit-cli/src/main.rs), and only without either falls back to the
compiled-in default. The harness does the same, through `load`, so `tkh eval` grades what
`tonekit assess` grades.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackFiles:
    """The pack and calibration a run graded with: what was read, where from, and sha256 of the
    bytes on disk."""

    pack_path: Path
    pack_toml: str
    pack_sha256: str
    calib_path: Path | None  # None: tonekit's compiled-in default
    calib_json: str | None
    calib_sha256: str | None
    calib_origin: str  # "--calib" or "beside the pack"; empty for the default

    def context(self) -> dict[str, str]:
        """The "pack" and "calibration" entries of a report's run context."""
        if self.calib_path is None:
            calibration = (
                "tonekit's compiled-in default (no --calib, and "
                f"{sibling(self.pack_path)} does not exist)"
            )
        else:
            calibration = (
                f"{self.calib_path} ({self.calib_origin}; sha256 {self.calib_sha256})"
            )
        return {
            "pack": f"{self.pack_path} (sha256 {self.pack_sha256})",
            "calibration": calibration,
        }


def sibling(pack: Path) -> Path:
    """`packs/cmn/cmn.toml` -> `packs/cmn/cmn.calib.json`, as the CLI's `with_extension` makes it."""
    return pack.with_suffix(".calib.json")


def _read(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    return data.decode("utf-8"), hashlib.sha256(data).hexdigest()


def load(pack: str | Path, calib: str | Path | None) -> PackFiles:
    """Read the pack TOML and its calibration: `calib` if given, else the file beside the pack if
    there is one, else none (the compiled-in default). Raises `OSError` for a file that cannot be
    read, and `UnicodeDecodeError` for one that is not UTF-8."""
    pack = Path(pack)
    pack_toml, pack_sha = _read(pack)
    if calib is not None:
        calib_path, origin = Path(calib), "--calib"
    elif sibling(pack).is_file():
        calib_path, origin = sibling(pack), "beside the pack"
    else:
        return PackFiles(pack, pack_toml, pack_sha, None, None, None, "")
    calib_json, calib_sha = _read(calib_path)
    return PackFiles(pack, pack_toml, pack_sha, calib_path, calib_json, calib_sha, origin)
