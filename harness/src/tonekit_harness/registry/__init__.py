"""The corpus registry: load corpora from the data root, select across them, refuse what the data
promises forbid (contracts.md section 3). The models and formats are `contracts.registry`'s.

    root = DataRoot(pack="packs/cmn/cmn.toml")           # $TONEKIT_DATA, else ~/tonekit-data
    fit = root.select(kinds=["public"], splits=["calib"]).for_fitting()   # a FittingSelection
    gate = root.select(["volunteers-*", "dj-*"], kinds=["recorded"], splits=["gate"], sets=["gate"])
    gate.for_gate()                                      # a GateSelection, or RefusalError saying why
    union = fit | gate                                   # compose (unchecked); speakers `corpus/speaker`

`tkh eval` and `tkh fit` take the same selections from the command line (`selectors`:
`--select CORPUS_GLOB[:SPLIT[,SPLIT]]`, repeatable) and grade or fit `Selection.grading_clips()`
from `Selection.audio_root` (`runs`); `tkh corpora` lists what is there (`corpora_cmd`).
"""

from .accent import accent_for
from .corpus import Corpus, load_corpus
from .errors import SelectionError
from .items import CorpusClip, qualify
from .refusals import Refusal, RefusalError
from .root import DataRoot
from .selection import FittingSelection, GateSelection, Selection

__all__ = [
    "Corpus",
    "CorpusClip",
    "DataRoot",
    "FittingSelection",
    "GateSelection",
    "Refusal",
    "RefusalError",
    "Selection",
    "SelectionError",
    "accent_for",
    "load_corpus",
    "qualify",
]
