#!/usr/bin/env bash
# Checks that every FFI function the generated C headers declare is defined in a static library:
# a missing one is a link error in Xcode ("Undefined symbol: _uniffi_tonekit_ffi_...").
#
# Usage: scripts/check-ffi-symbols.sh <libtonekit_ffi.a> <headers-dir>
# Works with GNU and Apple `nm` (Apple prefixes C symbols with an underscore).
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <static-library> <headers-dir>" >&2; exit 2; }
lib=$1
headers=$2
[ -f "$lib" ] || { echo "check-ffi-symbols: no such library: $lib" >&2; exit 1; }
ls "$headers"/*.h >/dev/null 2>&1 || { echo "check-ffi-symbols: no headers in $headers" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Function declarations look like `uint64_t uniffi_tonekit_ffi_fn_func_analyze(RustBuffer pcm, ...`.
cat "$headers"/*.h | grep -Eo '\b(uniffi|ffi)_tonekit[A-Za-z0-9_]*\(' | tr -d '(' | sort -u >"$tmp/declared"
# Defined, global text symbols (`T`), minus Apple's leading underscore. `nm` writes to a file
# instead of feeding the awk pipeline, and its exit status is checked: without that capture, a
# failing `nm` (missing, or an unreadable archive) made the script exit silently, with no message
# saying that `nm` was the problem.
if ! nm -g "$lib" >"$tmp/nm.out" 2>"$tmp/nm.err"; then
    echo "check-ffi-symbols: \`nm -g $lib\` failed:" >&2
    sed 's/^/  /' "$tmp/nm.err" >&2
    exit 1
fi
awk 'NF == 3 && $2 == "T" { print $3 }' "$tmp/nm.out" | sed 's/^_//' | sort -u >"$tmp/defined"

declared=$(wc -l <"$tmp/declared" | tr -d ' ')
[ "$declared" -gt 0 ] || { echo "check-ffi-symbols: found no FFI declarations in $headers" >&2; exit 1; }
comm -23 "$tmp/declared" "$tmp/defined" >"$tmp/missing"
if [ -s "$tmp/missing" ]; then
    echo "check-ffi-symbols: $(wc -l <"$tmp/missing" | tr -d ' ') of $declared declared functions are missing from $lib:" >&2
    sed 's/^/  /' "$tmp/missing" >&2
    exit 1
fi
echo "OK: all $declared FFI functions declared in the headers are defined in $(basename "$lib")"
