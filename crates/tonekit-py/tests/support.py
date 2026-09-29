"""Request builders shared by the tonekit_py tests (JSON in the facade's serde format)."""

from __future__ import annotations

RATE = 16_000


def candidate(cid: str, tones: list[str], labels: list[str] | None = None) -> dict:
    """A `Candidate` in the facade's JSON."""
    return {
        "id": cid,
        "targets": [
            {
                "tone": tone,
                "lexical_variants": [],
                "label": labels[i] if labels else None,
            }
            for i, tone in enumerate(tones)
        ],
    }


def standard_grading() -> dict:
    return {"accent": "cmn-standard", "style": None, "style_weight": 0.0}


def request_413() -> dict:
    """What `tonekit assess --tones "4 1 3" --labels "yi bei shui" --json` grades."""
    return {
        "grading": standard_grading(),
        "intended": candidate("intended", ["4", "1", "3"], ["yi", "bei", "shui"]),
        "distractors": [],
        "external": [],
        "compare_accents": [],
    }
