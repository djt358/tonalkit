# Verifying tonekit on the iOS Simulator (Task 12)

Checklist for a Mac. tonekit's top priority is that it runs on-device on iOS without issue
(spec §4.3). The Rust side of the iOS bridge was built and tested on Linux, but nothing here has
been compiled by Xcode or run on a Simulator yet: this is the run that proves it.

## What is already verified (Linux)

- `tonekit-ffi` builds and its Rust tests pass: the exported `Pack`, `analyze`, `decode`,
  `lattice` and `assess` reproduce `fixtures/spoken-413.assessment.json` within 1e-4.
- UniFFI generates the Swift bindings in library mode, and `scripts/check-swift-bindings.sh`
  checks the API shape and that every FFI function the C headers declare is defined in the static
  library.
- `cargo deny check` passes with the UniFFI crates (MPL-2.0 exceptions).

## What only this run can show

That the Rust static library links for `aarch64-apple-ios` and `aarch64-apple-ios-sim`, that the
generated Swift compiles under Xcode, that the XCFramework works through SwiftPM, and that the
same Rust code gives the same numbers when Swift calls it on iOS.

## Prerequisites

- An Apple-silicon Mac (the script builds the arm64 Simulator slice; an Intel Mac would also need
  `x86_64-apple-ios`, which the script does not build).
- Xcode 15 or newer with an iOS 17+ Simulator runtime (Xcode > Settings > Components). Open Xcode
  once and accept the licence, or run `sudo xcodebuild -license accept && sudo xcodebuild -runFirstLaunch`.
  Check with `xcodebuild -version` and `xcode-select -p` (it should point into the Xcode app).
- Rust via rustup (`rustup --version`). The script adds the two iOS targets itself; by hand:
  `rustup target add aarch64-apple-ios aarch64-apple-ios-sim`.
- The repository at the branch to test. About 3 GB of disk for the builds.

## The commands, in order

From the repository root:

```sh
# 1. Build the Rust static libraries for device and Simulator, generate the Swift bindings,
#    create build/Tonekit.xcframework and copy everything into swift/TonekitSmoke.
#    The first run compiles the whole dependency tree twice (device and Simulator) and the
#    bindings generator for the host: expect several minutes on a first run. Re-running is safe.
scripts/build-xcframework.sh

# 2. Run the Swift tests on the iOS Simulator.
cd swift/TonekitSmoke
xcodebuild test -scheme TonekitSmoke \
  -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tee ../../build/xcodebuild-test.log

# 3. The latency numbers.
grep -E 'measured \[Time|TONEKIT_LATENCY' ../../build/xcodebuild-test.log
```

The first `xcodebuild` also resolves the package and boots a Simulator, which takes a minute.

## What passing looks like

Step 1 ends with:

```
==> done
    XCFramework:  build/Tonekit.xcframework
    Swift bindings in swift/TonekitSmoke/Sources/Tonekit/Generated/
```

and before that, `OK: all 177 FFI functions declared in the headers are defined in libtonekit_ffi.a`
twice (once per library) and a line beginning `note: native-static-libs:` naming the system
libraries the static library needs.

Step 2 ends with all ten tests passing:

```
Test Suite 'SmokeTests' passed at ...
	 Executed 10 tests, with 0 failures (0 unexpected) in N seconds
** TEST SUCCEEDED **
```

`testSpokenFixtureMatchesCli` is the one that matters: it decodes the fixture WAV with
`AVAudioFile`, runs `analyze` and `assess` through the generated Swift on the Simulator, and
requires `overall` (0.730), every syllable's `pCorrect` (0.730, 0.734, 0.770) and `intendedRank`
(1) to match the CLI's JSON within 1e-4.

## The number to report back

Step 3 prints two things for `testAssessLatency` (one utterance of 4.39 s of audio: the 1.33 s
fixture three times with 200 ms of silence between the copies, the shortest tiling that reaches
the 3 s of the spec's latency budget (R52); `analyze` then `assess` of the matching nine-syllable
reading, cold-start register, no distractors):

```
Test Case '-[TonekitSmokeTests.SmokeTests testAssessLatency]' measured [Time, seconds] average: 0.xxx, ...
TONEKIT_LATENCY audio_ms=4390 analyze_plus_assess_median_ms=xxx.x p95_ms=xxx.x runs=20
```

Please send back the `TONEKIT_LATENCY` line, the stripped library size (next section), the Mac
model and chip, the macOS and Xcode versions.
This is informational in P0: the Simulator runs the Rust code natively on the Mac's CPU, so it
is not the device number. The P1 gate is p95 on a physical iPhone 12. For scale, the whole CLI run
on the 1.33 s fixture on this Linux dev box (process start, WAV, pack, analyse, assess) is about
250 ms. A result above a
couple of seconds means an unoptimised Rust build slipped in (the script builds `--release`).

## Library size

The spec (§10) budgets the stripped static library at 2 MB or less (without SwiftF0). Please send
back that number for the **device** slice (`aarch64-apple-ios`). Step 1 already prints the
stripped size of both slices at its end. To get it by hand, from the repository root after step 1:

```sh
target=$(cargo metadata --no-deps --format-version 1 | sed -n 's/.*"target_directory":"\([^"]*\)".*/\1/p')
cp "$target/aarch64-apple-ios/release/libtonekit_ffi.a" build/stripped-device.a
strip -S -x build/stripped-device.a      # debug and local symbols out, as a release app would have
ls -l build/stripped-device.a            # the number to report: bytes
```

The linked size of a minimal app is a different number (the linker drops what is unused, and adds
the Swift runtime glue); measuring it is out of scope for P0. If the stripped size is over
budget, these show where it goes:

```sh
xcrun size -m build/stripped-device.a                 # segment sizes per archive member
xcrun llvm-nm --size-sort --print-size --demangle build/stripped-device.a | tail -30   # largest symbols
```

The workspace sets no `[profile.release]`, so the library is built with cargo's release defaults
(no LTO, 16 codegen units). `lto = true` and `codegen-units = 1` are the first settings to try if
the size or the latency needs help; they are not applied in P0.

`rand` and `getrandom` are in the library even though tonekit never draws random numbers (the core
crates have no randomness): they arrive through `pyin → statrs → nalgebra → rand 0.8 →
getrandom 0.2` (`cargo tree -p tonekit-ffi -i rand`). `Package.swift` links `Security` (with
`iconv` and `Foundation`) as a first guess at the list rustc's `native-static-libs` note gives;
step 1 prints the real list, which decides, and it does not say which dependency needs which
library. `getrandom` 0.2 asks the OS for entropy through CommonCrypto (`CCRandomGenerateBytes`) on
iOS, so it is probably not what needs `Security`. To see which entropy API the library itself
calls:

```sh
nm -u build/stripped-device.a | grep -E 'SecRandom|CCRandom|getentropy'
```

## If something fails: the three most likely problems

Send back the first error message (not the last: later ones cascade) and the two log files
`build/rustc-*.log` and `build/xcodebuild-test.log`.

### 1. `Unable to find a device matching the provided destination`

`iPhone 15` is not among the Simulators of a newer Xcode, or the iOS runtime is not installed.

```sh
xcrun simctl list devices available | grep iPhone     # pick any listed name
xcodebuild test -scheme TonekitSmoke -destination 'platform=iOS Simulator,name=<that name>'
```

If the list is empty, install a Simulator runtime: Xcode > Settings > Components. The device name
does not matter to the test; the CI job pins `iPhone 15` on the macos-14 runner image.

### 2. The package is not wired up: hundreds of `cannot find type 'RustBuffer' in scope` errors, `does not contain a scheme named "TonekitSmoke"` (or `not configured for the test action`), or `binary target ... does not contain a binary artifact`

The last one means step 1 did not finish: `swift/TonekitSmoke/Frameworks/Tonekit.xcframework`
must exist. If the C module `TonekitFFI` is not wired up, you do **not** get
`No such module 'TonekitFFI'`: the generated Swift wraps `import TonekitFFI` in
`#if canImport(TonekitFFI)`, so the missing module goes unreported and everything that needs it
fails instead. The symptoms are hundreds of errors in `Sources/Tonekit/Generated/*.swift` such as
`cannot find type 'RustBuffer' in scope` and
`cannot find 'ffi_tonekit_..._rustbuffer_from_bytes' in scope`, or
`missing required module 'TonekitFFI'` in the test target. Check that the module map made it into
the Simulator slice:

```sh
# from swift/TonekitSmoke (where step 2 leaves you); from the repository root, prefix the path
# with swift/TonekitSmoke/
cat Frameworks/Tonekit.xcframework/ios-arm64-simulator/Headers/module.modulemap
```

It must say `module TonekitFFI` and list `tonekitFFI.h`, `tonekit_coreFFI.h` and
`tonekit_ffiFFI.h`, which must sit next to it. All three generated Swift files import the same C
module (`TonekitFFI`) on purpose: they pass `RustBuffer` values between each other, so it has to
be one type. If the scheme is the problem, list them with `xcodebuild -list` in
`swift/TonekitSmoke` and use `-scheme TonekitSmoke-Package`.

### 3. Undefined symbols when linking (`_iconv_open`, a `_Sec...` symbol, ...)

The static library needs some system libraries that `swift/TonekitSmoke/Package.swift` must name.
It links `iconv`, `Security` and `Foundation`. Step 1 prints the list rustc reports (the
`native-static-libs` line, also in `build/rustc-aarch64-apple-ios.log`). Add anything else to
`linkerSettings` (`.linkedLibrary("name")` for `-lname`, `.linkedFramework("Name")` for
`-framework Name`), then re-run step 2.

### Also possible

- **Swift compile errors** in `Sources/Tonekit/Generated/*.swift` (UniFFI 0.32.2 output, written for
  Swift 5.8+, so Xcode 15+) or in `Tests/TonekitSmokeTests/SmokeTests.swift`. The test file was
  parsed but never compiled, so a typo is possible: the error message names the line. Fix it and
  re-run step 2; the bindings need no rebuild.
- **`testAVAudioFileReadsTheFixture` fails but the others pass**: `AVAudioFile` could not read the
  WAVE_FORMAT_EXTENSIBLE float32 fixture. The other tests fall back to a plain RIFF reader, so
  they still exercise the Rust code; tell us, because Bendy will hit the same when it reads WAVs.
- **A number differs from the CLI by more than 1e-4** (`testSpokenFixtureMatchesCli`): a real
  platform difference in the DSP (libm, fused multiply-add). Send the failing values: that is the
  most valuable failure this run can produce.
- **`error: linker command failed ... built for newer iOS version`**: the script sets
  `IPHONEOS_DEPLOYMENT_TARGET=17.0` for the Rust objects; if it is overridden in your shell, unset
  it or set it to 17.0 or lower.
- **Intel Mac**: the Simulator needs an `x86_64-apple-ios` slice; the script does not build one.

## What the pieces are

| Path | What |
|---|---|
| `crates/tonekit-ffi/` | the exported Rust API (`Pack`, `analyze`, `decode`, `lattice`, `assess`) and the two generator binaries (`--features cli`) |
| `crates/tonekit-ffi/uniffi.toml` | one C module, `TonekitFFI`, for the three UniFFI crates (tonekit-core, tonekit, tonekit-ffi) |
| `scripts/build-xcframework.sh` | step 1 of the checklist |
| `scripts/check-swift-bindings.sh`, `scripts/check-ffi-symbols.sh` | checks that also run on Linux, in CI |
| `swift/TonekitSmoke/` | the SwiftPM package: binary target on the XCFramework, the generated bindings, the tests |
| `.github/workflows/ci.yml` | the `ffi` job (Linux): the bindings and FFI-symbol checks on every change |
| `.github/workflows/ios.yml` | the `ios` job (macos-14: the same two commands as above), on demand (Actions > ios > Run workflow) and on pull requests that touch the iOS bridge; its latency test runs in a quick mode (5 runs) |

Generated files (`build/`, `swift/TonekitSmoke/Frameworks/`, `.../Generated/`, `.../Fixtures/`)
are git-ignored.
