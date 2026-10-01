"""Speaker vocabulary shared by the session bundle and the corpus registry (contracts.md
sections 2 and 3). Enum values only, never free text: no names, emails or contact details."""

from __future__ import annotations

from typing import Literal

Background = Literal["native", "heritage", "learner", "prefer_not"]
GrewUpHearing = Literal["mainland", "taiwan", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not"]
