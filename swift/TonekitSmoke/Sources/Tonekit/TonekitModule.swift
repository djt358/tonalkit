// The Swift target `Tonekit` is the UniFFI-generated bindings for the Rust library: see
// Generated/, which scripts/build-xcframework.sh writes (it is not committed). The package does
// not resolve or compile until that script has run: it needs Frameworks/Tonekit.xcframework (the
// binary target) and the Tests/TonekitSmokeTests/Fixtures/ directory, which Package.swift declares
// as the test target's resources, so SwiftPM wants it even to resolve the package, not just to run
// the tests. This file only keeps the target's source directory non-empty before the bindings have
// been generated.

/// The one sample rate `analyze` accepts, in Hz. Resample anything else before calling it.
public let tonekitSampleRate: UInt32 = 16_000
