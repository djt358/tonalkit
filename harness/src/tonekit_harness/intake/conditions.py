"""The recording condition of a kit clip. The guide asks for a quiet-ish room and the phone's own
mic, and the speaker holds their own iPhone; nothing measures either. `uncontrolled` keeps these
clips apart from DJ's controlled `cafe` / `quiet` conditions (harness/corpus/PROTOCOL.md), and
`handheld` from his `arm` (arm's length)."""

from __future__ import annotations

from ..manifest import Condition

KIT_CONDITION = Condition(noise="uncontrolled", distance="handheld")
