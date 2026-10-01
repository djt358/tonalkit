"""The committed deck, kit/deck/s05-v1.toml and .json: what a volunteer reads this weekend. These
tests need C0's fix round (diag_context, text_traditional, diag_minimal groups)."""

import json
import re
import shutil
import subprocess
from collections import Counter

import pytest
from deck_support import DECK_DIR, SOURCES, needs_c0_fix

from tonekit_harness.contracts.deck import Deck, deck_sha256, load_deck, parse_deck
from tonekit_harness.contracts.lects import lect_rules
from tonekit_harness.deck_build.assemble import build_deck
from tonekit_harness.deck_build.emit import json_text, toml_text
from tonekit_harness.repo import repo_root

pytestmark = needs_c0_fix

TOML = DECK_DIR / "s05-v1.toml"
JSON = DECK_DIR / "s05-v1.json"
RULES = lect_rules("cmn")


@pytest.fixture(scope="module")
def deck() -> Deck:
    return load_deck(TOML)  # the contract's own check of every card: pairs, sandhi, one-tone errors


def of_set(deck, name):
    return [c for c in deck.card if c.set == name]


def test_the_deck_has_the_sets_and_counts_the_plan_asks_for(deck):
    counts = Counter(c.set for c in deck.card)
    assert counts == {"register": 8, "gate": 40, "diag_context": 7, "diag_t23": 8, "diag_minimal": 10, "diag_count": 3}
    assert len(deck.card) == 76
    assert (deck.deck.id, deck.deck.lect) == ("s05-v1", "cmn")


def test_every_card_is_unverified_until_djs_audit(deck):
    assert {c.status for c in deck.card} == {"unverified"}


def test_every_card_has_traditional_text_of_the_same_length(deck):
    assert all(c.text_traditional is not None and len(c.text_traditional) == len(c.text) for c in deck.card)


def test_pinyin_is_the_surface_form_with_tone_marks_and_labels_are_toneless(deck):
    for c in deck.card:
        shown = RULES.parse_pinyin(c.pinyin)
        assert [s.tone for s in shown] == c.produced_tones, c.id
        assert not re.search(r"[0-9]", c.pinyin), c.id  # tone marks, not numbers
        for label in c.intended.labels:
            assert re.fullmatch(r"[a-zü]+", label), (c.id, label)


def test_no_card_has_a_neutral_tone(deck):
    # Taiwan Mandarin says many syllables the mainland reduces; a correct reading must not be graded
    # against a tone one accent does not make (R?: no neutral tones in v1)
    assert not [c.id for c in deck.card if "5" in c.produced_tones or "5" in c.intended.tones]


def test_no_phrase_holds_a_citation_tone_where_speakers_produce_sandhi(deck):
    for c in deck.card:
        citation = [s.tone for s in RULES.parse_pinyin(c.citation_pinyin)]
        if c.context == "isolated":
            assert c.produced_tones == citation, c.id
        elif c.set in {"gate", "diag_context", "diag_count"}:
            assert c.produced_tones[0] in {"2", "4"} or c.text.strip("嗯就是…").startswith(("不", "水")), c.id
    for c in of_set(deck, "gate"):
        assert c.produced_tones[0] in {"2", "4"}  # 一 is yì or yí in every gate phrase, never yī


def test_the_gate_is_twenty_pairs_covering_the_sandhi_cases(deck):
    gate = of_set(deck, "gate")
    assert Counter(c.label for c in gate) == {"correct": 20, "tone_error": 20}
    correct = [c for c in gate if c.label == "correct"]
    after_yi = Counter(RULES.parse_pinyin(c.citation_pinyin)[1].tone for c in correct)
    assert after_yi == {"1": 5, "2": 4, "3": 5, "4": 6}
    assert Counter(c.produced_tones[0] for c in correct) == {"4": 14, "2": 6}
    runs = [c for c in correct if "3-3" in "-".join(s.tone for s in RULES.parse_pinyin(c.citation_pinyin))]
    assert len(runs) >= 2 and all(c.produced_tones[1:] == ["2", "3"] for c in runs)  # 一碗水 is yì wán shuǐ
    for c in gate:
        assert c.text.startswith("一") and len(c.text) == 3 and c.context == "phrase"
        if c.label == "tone_error":
            assert re.fullmatch(r"Read it as written: . as in .+ \(.+\)\.", c.prompt_note), c.id


def test_error_cards_are_made_of_other_characters_than_their_correct_twin(deck):
    cards = {c.id: c for c in deck.card}
    for c in of_set(deck, "gate") + of_set(deck, "diag_t23"):
        if c.label == "tone_error":
            twin = cards[c.pair + "-c"]
            assert sum(a != b for a, b in zip(c.text, twin.text, strict=True)) == 1, c.id


def test_the_register_set_is_eight_clips_of_the_four_tones_said_one_by_one(deck):
    register = of_set(deck, "register")
    assert len(register) == 8 and {c.text for c in register} == {"妈麻马骂"}
    assert {(c.context, tuple(c.produced_tones)) for c in register} == {("isolated", ("1", "2", "3", "4"))}


def test_every_minimal_word_is_correct_and_lists_the_other_as_its_distractor(deck):
    minimal = of_set(deck, "diag_minimal")
    assert {c.label for c in minimal} == {"correct"} and len({c.pair for c in minimal}) == 5
    by_pair = {}
    for c in minimal:
        by_pair.setdefault(c.pair, []).append(c)
    for members in by_pair.values():
        assert len(members) == 2
        for c in members:
            others = [m for m in members if m is not c]
            assert [d.id for d in c.distractors] == [m.intended.id for m in others]
            assert [d.labels for d in c.distractors] == [m.intended.labels for m in others]  # same syllable...
            assert [d.tones for d in c.distractors] != [c.intended.tones]  # ...another tone
            assert c.context == "isolated"


def test_the_context_contrasts_are_the_ones_dj_named(deck):
    cards = {c.text: c for c in of_set(deck, "diag_context")}
    assert {t: (c.context, c.pinyin) for t, c in cards.items()} == {
        "一": ("isolated", "yī"), "一杯": ("phrase", "yì bēi"), "一块": ("phrase", "yí kuài"),
        "不": ("isolated", "bù"), "不对": ("phrase", "bú duì"),
        "水": ("isolated", "shuǐ"), "水果": ("phrase", "shuí guǒ"),
    }  # fmt: skip


def test_t23_pairs_swap_second_and_third_tones_and_include_the_half_third(deck):
    t23 = of_set(deck, "diag_t23")
    assert len({c.pair for c in t23}) == 4
    cards = {c.id: c for c in t23}
    for pair in {c.pair for c in t23}:
        c, e = cards[f"{pair}-c"], cards[f"{pair}-e"]
        (swap,) = [{a, b} for a, b in zip(c.produced_tones, e.produced_tones, strict=True) if a != b]
        assert swap == {"2", "3"}, pair
    half_third = [c for c in t23 if c.label == "correct" and c.produced_tones[0] == "3" and len(c.produced_tones) > 1]
    assert half_third  # a third tone before another syllable


def test_count_cards_ask_for_the_spell_only(deck):
    count = of_set(deck, "diag_count")
    assert len(count) == 3
    for c in count:
        assert len(c.text) > len(c.produced_tones) and "…" in c.text
        assert len(c.produced_tones) == 3 and c.label == "correct" and c.prompt_note


def test_the_committed_files_are_what_the_sources_build():
    built = build_deck(SOURCES)
    assert TOML.read_text(encoding="utf-8") == toml_text(built.data)
    assert JSON.read_text(encoding="utf-8") == json_text(built.data)


def test_the_json_is_the_same_deck_in_the_shape_the_kit_loads(deck):
    data = json.loads(JSON.read_text(encoding="utf-8"))
    assert data == deck.model_dump(mode="json", exclude_none=True)
    assert parse_deck(data).card == deck.card
    assert set(data) == {"deck", "card"} and all(
        "pair" not in c for c in data["card"] if c["set"] in {"register", "diag_context", "diag_count"}
    )


def test_the_kit_s_own_loader_reads_the_json_and_hashes_its_bytes(tmp_path):
    loader = repo_root() / "kit" / "app" / "deck.js"
    node = shutil.which("node")
    if node is None or not loader.exists():
        pytest.skip("needs node and kit/app/deck.js (P4's kit)")
    script = tmp_path / "load.mjs"
    script.write_text(
        f"""import {{ readFileSync }} from "node:fs";
import {{ loadDeck }} from {json.dumps(loader.as_uri())};
const bytes = readFileSync({json.dumps(str(JSON))});
const fetcher = async () => ({{ ok: true, status: 200, arrayBuffer: async () => Uint8Array.from(bytes).buffer }});
const deck = await loadDeck({{ id: "s05-v1", fetcher, dev: true }});
console.log(JSON.stringify({{ id: deck.id, n: deck.cards.length, sha: deck.sha256 }}));
""",
        encoding="utf-8",
    )
    out = subprocess.run([node, str(script)], capture_output=True, text=True, check=True, cwd=tmp_path).stdout
    loaded = json.loads(out)
    assert loaded == {"id": "s05-v1", "n": 76, "sha": deck_sha256(JSON)}


def test_the_sources_hold_no_gmeasure_table():
    # DJ's real g_measure CSV never enters the repository; the stand-in is flagged by its name
    assert sorted(p.name for p in SOURCES.iterdir()) == sorted(
        ["deck.toml", "diag_context.csv", "diag_count.csv", "diag_minimal.csv", "diag_t23.csv",
         "gate_standin.csv", "register.csv", "tone_variants.csv"]
    )  # fmt: skip
