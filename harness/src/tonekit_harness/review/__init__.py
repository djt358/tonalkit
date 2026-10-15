"""`tkh review`: a local page for listening to each clip of a corpus and recording what was
actually said, which `tkh relabel` then applies. The page lives under the data root (it links the
volunteers' audio and names their clips), opens from disk, loads nothing from the network, and
keeps its decisions in the browser until they are exported. One module per concern: `cards` finds
what each card showed, `scorer` reads `tkh eval`'s view, `order` puts the doubtful clips first,
`view` assembles the page's data, `page` writes the page."""
