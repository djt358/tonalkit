#!/usr/bin/env bash
# Fails if any audio file other than the shared fixture is tracked. The repository is public, and
# recordings of people (volunteers, DJ) must never be committed: they live under $TONEKIT_DATA.
set -euo pipefail
allowed='^fixtures/spoken-413\.wav$'
tracked=$(git ls-files -z | tr '\0' '\n' |
    grep -iE '\.(wav|m4a|mp3|aac|caf|flac|ogg|opus|webm|aif|aiff)$' | grep -vE "$allowed" || true)
if [ -n "$tracked" ]; then
    echo "check-no-audio: audio files are tracked; recordings belong under \$TONEKIT_DATA:" >&2
    echo "$tracked" | sed 's/^/  /' >&2
    exit 1
fi
echo "OK: no tracked audio besides the fixture"
