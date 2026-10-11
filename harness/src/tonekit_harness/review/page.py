"""The review page: one self-contained HTML file, written to `review/<corpus>/index.html` under the
data root. Its script, style and data are inline because a page opened from disk cannot fetch a
file beside it; the data is a JSON block, and the Content-Security-Policy allows exactly the inline
script and style (by hash) and media from the page's own disk, nothing from the network."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from importlib import resources
from pathlib import Path

from ..atomic import write_text_atomic
from ..intake import layout

PAGE = "index.html"


def _asset(name: str) -> str:
    return resources.files(__package__).joinpath("assets", name).read_text(encoding="utf-8")


def _sha256(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def content_security_policy(script: str, style: str) -> str:
    """No source on the network: the inline script and style by hash, media from the page's own
    disk (`'self'`, and `file:` for browsers whose `'self'` does not cover it), nothing else."""
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src {_sha256(script)}",
            f"style-src {_sha256(style)}",
            "media-src 'self' file:",
            "connect-src 'none'",
            "img-src 'none'",
            "form-action 'none'",
            "base-uri 'none'",
        ]
    )


def _data_block(data: dict) -> str:
    """The page data as JSON that cannot end its `<script>` block early."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render(data: dict) -> str:
    script, style = _asset("review.js"), _asset("review.css")
    title = f"Listen and relabel: {data['corpus']}"
    replacements = {
        "{{CSP}}": html.escape(content_security_policy(script, style), quote=True),
        "{{TITLE}}": html.escape(title),
        "{{STYLE}}": style,
        "{{DATA}}": _data_block(data),
        "{{SCRIPT}}": script,
    }
    # one pass: a value is never searched for another token
    return re.sub(r"\{\{[A-Z]+\}\}", lambda m: replacements[m.group(0)], _asset("review.html"))


def write_page(root: Path, corpus_id: str, data: dict) -> Path:
    """Write the page under the data root; returns its path."""
    path = layout.review_dir(root, corpus_id) / PAGE
    write_text_atomic(path, render(data))
    return path
