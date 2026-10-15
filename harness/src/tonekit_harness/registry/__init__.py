"""The corpus registry: load corpora from the data root, select across them, refuse what the data
promises forbid (contracts.md section 3). The models and formats are `contracts.registry`'s.

    root = DataRoot()                                    # $TONEKIT_DATA, else ~/tonekit-data
    fit = root.select(kinds=["public"], splits=["calib"]).for_fitting()
    gate = root.select(["volunteers-*", "dj-*"], kinds=["recorded"], splits=["gate"], sets=["gate"])
    gate.for_gate()                                      # raises RefusalError if it may not be graded
    union = fit | gate                                   # compose; speaker ids are `corpus/speaker`
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
