"""`tkh fit`: fit the pack's tone templates and the calibration on calibration speakers (rulings
R103, R108, R109).

Observations come from a forced decode of what each calibration clip's speaker was asked to
produce (`observe`); the fits read them (`unpitched` for the evidence of unpitched syllables,
`tail` for that of creaky tails, `templates` for the tone shapes and their spreads), and `cli`
writes a fitted pack and
calibration. Only speakers whose corpus split is `calib` are ever fitted on.
"""
