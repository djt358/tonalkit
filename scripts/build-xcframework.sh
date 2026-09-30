#!/usr/bin/env bash
# Builds tonekit for iOS and packages it for the Swift package in swift/TonekitSmoke:
#
#   1. Rust static libraries for the device (aarch64-apple-ios) and the Apple-silicon simulator
#      (aarch64-apple-ios-sim).
#   2. Swift bindings, C headers and a module map, generated from a built library (UniFFI library
#      mode) by the pinned `uniffi-bindgen-swift`.
#   3. build/Tonekit.xcframework (`xcodebuild -create-xcframework`).
#   4. The XCFramework, the generated Swift and the test resources copied into swift/TonekitSmoke.
#
# macOS with Xcode only. Safe to re-run: every output is rebuilt from scratch. Nothing generated
# is committed (build/ and the copied files are git-ignored).
#
# Usage: scripts/build-xcframework.sh
#   IPHONEOS_DEPLOYMENT_TARGET  minimum iOS version of the Rust objects (default 17.0, the
#                               Swift package's platform)
set -euo pipefail

cd "$(dirname "$0")/.."
root=$PWD
build=$root/build
pkg=$root/swift/TonekitSmoke
ffi_module=TonekitFFI   # keep in step with crates/tonekit-ffi/uniffi.toml and Package.swift
targets=(aarch64-apple-ios aarch64-apple-ios-sim)

step() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nbuild-xcframework: %s\n' "$*" >&2; exit 1; }

# Prints the size of each slice's static library after `strip -S -x` (debug and local symbols
# out), measured on a copy in build/. Informational: the spec (section 10) budgets 2 MB stripped
# for the device slice, and nothing here fails the build, not even a missing `strip`.
report_sizes() {
    command -v strip >/dev/null || { echo "    (no strip on the PATH: sizes not reported)"; return 0; }
    local triple lib copy bytes
    for triple in "${targets[@]}"; do
        lib=$target_dir/$triple/release/libtonekit_ffi.a
        copy=$build/stripped-$triple.a
        if cp "$lib" "$copy" && strip -S -x "$copy" 2>/dev/null; then
            bytes=$(wc -c <"$copy" | tr -d ' ')
            printf '    %-22s %9s bytes stripped (%s KiB)' "$triple" "$bytes" "$((bytes / 1024))"
            if [ "$triple" = aarch64-apple-ios ] && [ "$bytes" -gt 2097152 ]; then
                printf '  <- over the 2 MB budget'
            fi
            printf '\n'
        else
            echo "    $triple: could not strip a copy of $lib; size not reported"
        fi
        rm -f "$copy"
    done
    return 0
}

# ---- prerequisites -------------------------------------------------------------------------

step "checking prerequisites"
[ "$(uname -s)" = Darwin ] ||
    fail "this script needs macOS and Xcode. On Linux, scripts/check-swift-bindings.sh checks what can be checked."
command -v xcodebuild >/dev/null ||
    fail "xcodebuild not found. Install Xcode, then run: sudo xcode-select -s /Applications/Xcode.app"
command -v xcrun >/dev/null || fail "xcrun not found. Install Xcode."
command -v cargo >/dev/null || fail "cargo not found. Install Rust from https://rustup.rs"
command -v rustup >/dev/null || fail "rustup not found. Install Rust from https://rustup.rs"
for sdk in iphoneos iphonesimulator; do
    xcrun --sdk "$sdk" --show-sdk-path >/dev/null 2>&1 ||
        fail "the $sdk SDK is missing. Open Xcode once to finish installing it (Settings > Components), then re-run."
done
xcodebuild -version | sed 's/^/    /'
echo "    $(rustc --version)"

export IPHONEOS_DEPLOYMENT_TARGET=${IPHONEOS_DEPLOYMENT_TARGET:-17.0}
echo "    IPHONEOS_DEPLOYMENT_TARGET=$IPHONEOS_DEPLOYMENT_TARGET"

target_dir=${CARGO_TARGET_DIR:-}
if [ -z "$target_dir" ]; then
    target_dir=$(cargo metadata --no-deps --format-version 1 |
        sed -n 's/.*"target_directory":"\([^"]*\)".*/\1/p')
fi
[ -n "$target_dir" ] || fail "could not work out cargo's target directory (set CARGO_TARGET_DIR)"

# ---- 1. Rust static libraries --------------------------------------------------------------

step "adding the Rust targets (a no-op when already installed)"
rustup target add "${targets[@]}"

mkdir -p "$build"
for triple in "${targets[@]}"; do
    step "building libtonekit_ffi.a for $triple (release)"
    # `cargo rustc --crate-type staticlib` builds just the static library. `cargo build` would
    # also link the cdylib, which iOS does not need. The log keeps rustc's note on which system
    # libraries the static library needs at link time.
    cargo rustc -p tonekit-ffi --lib --release --target "$triple" --crate-type staticlib \
        -- --print native-static-libs 2>&1 | tee "$build/rustc-$triple.log"
    [ -f "$target_dir/$triple/release/libtonekit_ffi.a" ] ||
        fail "expected $target_dir/$triple/release/libtonekit_ffi.a after the build"
done
echo
echo "    system libraries the static library needs (Package.swift links iconv, Security and Foundation;"
echo "    if this list names others, add them to linkerSettings there):"
grep -h 'native-static-libs' "$build/rustc-aarch64-apple-ios.log" | sed 's/^/    /' ||
    echo "    (no note this time: cargo reused an earlier build; touch crates/tonekit-ffi/src/lib.rs to see it)"

# ---- 2. Swift bindings, headers, module map ------------------------------------------------

step "building the bindings generator (host)"
cargo build -p tonekit-ffi --features cli --bin uniffi-bindgen-swift
bindgen=$target_dir/debug/uniffi-bindgen-swift
[ -x "$bindgen" ] || fail "expected $bindgen after the build"

step "generating Swift bindings, headers and module map (library mode)"
rm -rf "$build/swift" "$build/headers"
# Any of the static libraries carries the UniFFI metadata; the simulator one is as good as any.
"$bindgen" \
    --swift-sources --headers --modulemap \
    --module-name "$ffi_module" --modulemap-filename module.modulemap \
    --metadata-no-deps --config crates/tonekit-ffi/uniffi.toml \
    "$target_dir/aarch64-apple-ios-sim/release/libtonekit_ffi.a" "$build/swift"
ls "$build/swift" | sed 's/^/    /'
compgen -G "$build/swift/*.swift" >/dev/null ||
    fail "uniffi-bindgen-swift generated no Swift from $target_dir/aarch64-apple-ios-sim/release/libtonekit_ffi.a"
for swift in "$build"/swift/*.swift; do
    grep -q "^import $ffi_module\$" "$swift" ||
        fail "$(basename "$swift") does not import $ffi_module: is crates/tonekit-ffi/uniffi.toml being read?"
done

# The XCFramework's Headers/: the three C headers and the module map, nothing else.
mkdir -p "$build/headers"
cp "$build"/swift/*.h "$build/swift/module.modulemap" "$build/headers/"

# ---- 3. XCFramework ------------------------------------------------------------------------

step "checking that both libraries define every function the headers declare"
for triple in "${targets[@]}"; do
    scripts/check-ffi-symbols.sh "$target_dir/$triple/release/libtonekit_ffi.a" "$build/headers"
done

step "creating build/Tonekit.xcframework"
rm -rf "$build/Tonekit.xcframework"
xcodebuild -create-xcframework \
    -library "$target_dir/aarch64-apple-ios/release/libtonekit_ffi.a" -headers "$build/headers" \
    -library "$target_dir/aarch64-apple-ios-sim/release/libtonekit_ffi.a" -headers "$build/headers" \
    -output "$build/Tonekit.xcframework"

# ---- 4. The Swift package ------------------------------------------------------------------

step "copying into swift/TonekitSmoke"
# The XCFramework: SwiftPM wants a binary target inside the package directory.
rm -rf "$pkg/Frameworks/Tonekit.xcframework"
mkdir -p "$pkg/Frameworks"
cp -R "$build/Tonekit.xcframework" "$pkg/Frameworks/"

# The generated Swift (three files, one per UniFFI crate).
rm -rf "$pkg/Sources/Tonekit/Generated"
mkdir -p "$pkg/Sources/Tonekit/Generated"
cp "$build"/swift/*.swift "$pkg/Sources/Tonekit/Generated/"

# Test resources: the shared fixture pair and the pack, from their single source of truth.
resources=$pkg/Tests/TonekitSmokeTests/Resources
mkdir -p "$resources"
cp fixtures/spoken-413.wav fixtures/spoken-413.assessment.json "$resources/"
cp packs/cmn/cmn.toml packs/cmn/cmn.calib.json "$resources/"

step "stripped size of each slice's static library (budget for the device slice: 2 MB)"
report_sizes

step "done"
echo "    XCFramework:  build/Tonekit.xcframework"
echo "    Swift bindings in swift/TonekitSmoke/Sources/Tonekit/Generated/"
echo
echo "Next, on the iOS Simulator (see docs/ios-verification.md):"
echo "    cd swift/TonekitSmoke && xcodebuild test -scheme TonekitSmoke \\"
echo "        -destination 'platform=iOS Simulator,name=iPhone 15'"
