#!/usr/bin/env bash
# Assembles the kit's static site into DIR, the same layout as kit/ itself:
#   index.html (-> app/), app/ (the kit, stand-ins included for ?dev=1), copy.json, CONSENT.md,
#   deck/<id>.json.
# Used by .github/workflows/pages.yml and by the e2e test. Missing content is allowed: the app
# falls back to app/standin/ for copy, and refuses to run outside ?dev=1 without the real
# CONSENT.md or an approved deck, so volunteers never see stand-ins.
set -euo pipefail
[ $# -eq 1 ] || { echo "usage: kit/assemble-site.sh DIR" >&2; exit 2; }
out=$1
kit=$(cd "$(dirname "$0")" && pwd)

rm -rf "$out"
mkdir -p "$out/deck"
cp "$kit/index.html" "$out/"
cp -R "$kit/app" "$out/app"
for f in copy.json CONSENT.md; do
    if [ -f "$kit/$f" ]; then
        cp "$kit/$f" "$out/"
    else
        echo "assemble-site: kit/$f not found; the app uses app/standin/ (?dev=1 only for consent)" >&2
    fi
done
shopt -s nullglob
decks=("$kit"/deck/*.json)
if [ ${#decks[@]} -gt 0 ]; then
    cp "${decks[@]}" "$out/deck/"
else
    echo "assemble-site: no kit/deck/*.json yet; only ?dev=1 (the stand-in deck) works" >&2
fi
# The site never carries audio.
if find "$out" -type f | grep -iqE '\.(wav|m4a|mp3|aac|caf|flac|ogg|opus|webm|aif|aiff)$'; then
    echo "assemble-site: audio files found in the site" >&2
    exit 1
fi
echo "assembled $out"
