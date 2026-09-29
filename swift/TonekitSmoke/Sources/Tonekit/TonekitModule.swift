// The Swift target `Tonekit` is the UniFFI-generated bindings for the Rust library: see
// Generated/, which scripts/build-xcframework.sh writes (it is not committed). This file is here
// so that the package resolves before the bindings have been generated.

/// The one sample rate `analyze` accepts, in Hz. Resample anything else before calling it.
public let tonekitSampleRate: UInt32 = 16_000
