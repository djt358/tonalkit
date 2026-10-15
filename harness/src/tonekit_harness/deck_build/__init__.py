"""The deck builder: the CSV sources under kit/deck/sources/ become the deck contract file
(`kit/deck/<id>.toml`, docs/s05/contracts.md section 1) and the same cards as JSON for the kit.

Every card the builder makes is checked by the contract models (`contracts.deck`), never by rules
copied here. The builder is cmn-specific: pinyin rendering and the tone-variant lexicon are
Mandarin's."""
