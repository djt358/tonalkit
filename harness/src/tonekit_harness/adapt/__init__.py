"""`tkh adapt`: a downloaded public corpus (AISHELL-3, THCHS-30) becomes a tonekit corpus under the
data root (docs/s05/contracts.md sections 3 and 4): kind `public`, speakers in hashed splits,
16 kHz mono PCM16 audio, and one `sentence` row (R121) per utterance whose produced tones its
transcript settles (`reading`, R122). One module per concern: each corpus's reader says where its
files are and what its transcripts mean; `run` stages and commits the corpus like intake."""
