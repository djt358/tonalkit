"""`tkh relabel`: apply what a listener heard (the review page's export) to a corpus manifest.
Each clip's row is rebuilt from the row intake wrote (the card's reading) and the clip's latest
decision; a log under the corpus keeps every decision and every row change (contracts.md
section 7). One module per concern: `state` reads the corpus and the log, `rules` relabels one row,
`pairs` keeps the gate's pairs whole, `plan` works out the change, `apply` writes it."""
