"""Which condition a synthetic clip belongs to in the bakeoff: `clean` (anything but the `noise`
family), or a noise clip in the bucket of its SNR."""

from __future__ import annotations

from .manifest import Clip

CLEAN = "clean"
NOISE_BUCKETS_DB = (5.0, 10.0, 20.0)  # a noise clip is grouped under the nearest of these SNRs


def condition(clip: Clip) -> str:
    """`"clean"` for every clip but the `noise` family's, which is `"noise ~N dB"` for the nearest
    SNR bucket N (the lower on a tie). A noise row with no `snr_db` is grouped under its own
    `condition.noise`."""
    synthetic = clip.synthetic or {}
    if synthetic.get("family") != "noise":
        return CLEAN
    snr = (synthetic.get("params") or {}).get("snr_db")
    if not isinstance(snr, int | float):
        return clip.condition.noise
    nearest = min(NOISE_BUCKETS_DB, key=lambda bucket: abs(snr - bucket))
    return f"noise ~{nearest:g} dB"


def order(name: str) -> tuple[int, str]:
    """A sort key: `clean`, then the noise buckets by SNR, then any other condition by name."""
    known = [CLEAN, *(f"noise ~{b:g} dB" for b in NOISE_BUCKETS_DB)]
    return (known.index(name), "") if name in known else (len(known), name)


def buckets_text() -> str:
    """The buckets as a phrase for the report: `5, 10 and 20 dB`."""
    names = [f"{b:g}" for b in NOISE_BUCKETS_DB]
    return (", ".join(names[:-1]) + " and " if len(names) > 1 else "") + f"{names[-1]} dB"
