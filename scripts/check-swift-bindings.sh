#!/usr/bin/env bash
# Generates the Swift bindings from a host build of tonekit-ffi (UniFFI library mode) into
# build/swift/ and checks that the generated API is what the Swift package and its tests expect.
#
# Runs on Linux and macOS and needs no Swift toolchain, so CI can run it on every push. It proves
# that the bindings generate and have the right shape; it cannot prove that the Swift compiles or
# that the XCFramework links (it does check that no declared FFI symbol is missing from the static
# library): that is scripts/build-xcframework.sh plus the iOS Simulator tests.
#
# Usage: scripts/check-swift-bindings.sh
set -euo pipefail

cd "$(dirname "$0")/.."
root=$PWD
target_dir=${CARGO_TARGET_DIR:-$root/target}
out=$root/build/swift
ffi_module=TonekitFFI  # keep in step with crates/tonekit-ffi/uniffi.toml

fail() { echo "check-swift-bindings: $*" >&2; exit 1; }

case "$(uname -s)" in
    Darwin) lib=$target_dir/debug/libtonekit_ffi.dylib ;;
    *) lib=$target_dir/debug/libtonekit_ffi.so ;;
esac

echo "==> building tonekit-ffi (host, with the bindings generator)"
cargo build -p tonekit-ffi --features cli
[ -f "$lib" ] || fail "expected $lib after the build"

echo "==> generating Swift bindings into ${out#"$root"/}"
rm -rf "$out"
"$target_dir/debug/uniffi-bindgen-swift" \
    --swift-sources --headers --modulemap \
    --module-name "$ffi_module" --modulemap-filename module.modulemap \
    --metadata-no-deps --config crates/tonekit-ffi/uniffi.toml \
    "$lib" "$out"

echo "==> checking the generated API"
# `have FILE PATTERN`: the extended regex PATTERN matches in FILE.
have() {
    grep -Eq -- "$2" "$out/$1" || fail "$1 lacks: $2"
}

# One Swift file, one header per UniFFI crate, and one module map that lists all three headers.
for crate in tonekit_core tonekit tonekit_ffi; do
    [ -f "$out/$crate.swift" ] || fail "missing $crate.swift"
    [ -f "$out/${crate}FFI.h" ] || fail "missing ${crate}FFI.h"
    have module.modulemap "header \"${crate}FFI.h\""
    # Every Swift file imports the ONE shared C module: the converters cross files with a
    # RustBuffer, which must be the same type on both sides.
    have "$crate.swift" "^import $ffi_module\$"
    [ "$(grep -Ec '^import [A-Za-z_]+FFI$' "$out/$crate.swift")" = 1 ] ||
        fail "$crate.swift imports more than one FFI module"
done
have module.modulemap "^module $ffi_module \\{"

# The functions and the Pack class (tonekit_ffi.swift).
have tonekit_ffi.swift 'public func analyze\(pcm: \[Float\], sampleRate: UInt32, register: Register\? = nil, externalF0: F0Track\? = nil\)[[:space:]]*throws[[:space:]]*-> Analysis'
have tonekit_ffi.swift 'public func decode\(analysis: Analysis, pack: Pack, grading: GradingTarget, candidates: \[Candidate\]\)[[:space:]]*throws[[:space:]]*-> DecodeResult'
have tonekit_ffi.swift 'public func lattice\(analysis: Analysis, pack: Pack, grading: GradingTarget\)[[:space:]]*throws[[:space:]]*-> ToneLattice'
have tonekit_ffi.swift 'public func assess\(analysis: Analysis, pack: Pack, request: AssessRequest\)[[:space:]]*throws[[:space:]]*-> UtteranceAssessment'
have tonekit_ffi.swift '^open class Pack: PackProtocol'
have tonekit_ffi.swift 'public static func fromToml\(packToml: String, calibJson: String\? = nil\)[[:space:]]*throws[[:space:]]*-> Pack'
have tonekit_ffi.swift 'func lect\(\)[[:space:]]*-> Lect'
have tonekit_ffi.swift 'func baseAccent\(\)[[:space:]]*-> AccentId'
have tonekit_ffi.swift 'func inventory\(\)[[:space:]]*-> \[ToneId\]'

# The request (tonekit.swift).
have tonekit.swift '^public struct AssessRequest'
have tonekit.swift 'public var compareAccents: \[AccentId\]'

# The shared types, the error and the four ids (tonekit_core.swift).
for name in Analysis F0Track F0Frame Register Candidate ToneTarget GradingTarget \
    UtteranceAssessment SyllableAssessment DecodeResult ToneLattice; do
    have tonekit_core.swift "^public struct $name: "
done
for name in Measured MeasureIssue DeltaKind Evidence EvidenceKind RegisterSource; do
    have tonekit_core.swift "^public enum $name: "
done
# `public` and `enum` are on separate lines in the generated error.
have tonekit_core.swift '^enum AssessError: Swift.Error'
have tonekit_core.swift 'case UnsupportedSampleRate\(got: UInt32'
have tonekit_core.swift 'case Pack\(message: String'
for id in Lect AccentId ToneId CandidateId; do
    have tonekit_core.swift "^public typealias $id = String\$"
done
have tonekit_core.swift 'public var pCorrect: Float'
have tonekit_core.swift 'public var intendedRank: UInt32'
have tonekit_core.swift 'public var overall: Float\?'

# The three headers and the module map are one clang module: this is what Swift's `import
# TonekitFFI` sees inside the XCFramework. (Linux clang has no Darwin module, so drop that line.)
if command -v clang >/dev/null; then
    echo "==> checking that the headers form one clang module"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    cp "$out"/*.h "$tmp/"
    if [ "$(uname -s)" = Darwin ]; then
        cp "$out/module.modulemap" "$tmp/module.modulemap"
    else
        grep -v 'use "Darwin"' "$out/module.modulemap" >"$tmp/module.modulemap"
    fi
    printf '#include "tonekit_coreFFI.h"\n#include "tonekitFFI.h"\n#include "tonekit_ffiFFI.h"\nRustBuffer f(RustBuffer b) { return b; }\n' >"$tmp/t.c"
    clang -fmodules -fmodules-cache-path="$tmp/cache" -fmodule-map-file="$tmp/module.modulemap" \
        -I"$tmp" -fsyntax-only -x c "$tmp/t.c" || fail "the headers and module map do not compile as one module"
else
    echo "==> (no clang here: skipping the module map check)"
fi

echo "==> checking that the static library defines every function the headers declare"
scripts/check-ffi-symbols.sh "$target_dir/debug/libtonekit_ffi.a" "$out"

echo "OK: Swift bindings generated in ${out#"$root"/} and have the expected API"
