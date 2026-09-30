// swift-tools-version: 5.9
//
// The iOS Simulator smoke test for tonekit (Task 12): the Rust library, compiled to an XCFramework,
// called from Swift through the UniFFI-generated bindings.
//
// Everything this package needs beyond what is committed is produced by
// `scripts/build-xcframework.sh` (run it first; it is safe to re-run):
//
//   Frameworks/Tonekit.xcframework      the Rust static libraries (device + simulator) with the C
//                                       headers and module map for the C module `TonekitFFI`
//   Sources/Tonekit/Generated/*.swift   the generated bindings (one file per UniFFI crate)
//   Tests/TonekitSmokeTests/Resources/  the fixture pair and the pack, copied from fixtures/ and
//                                       packs/cmn/
import PackageDescription

let package = Package(
    name: "TonekitSmoke",
    platforms: [.iOS(.v17)],
    products: [
        .library(name: "TonekitSmoke", targets: ["Tonekit"]),
    ],
    targets: [
        // The C module is called `TonekitFFI` (its module.modulemap is inside the XCFramework, and
        // the generated Swift does `import TonekitFFI`).
        .binaryTarget(
            name: "TonekitFFI",
            path: "Frameworks/Tonekit.xcframework"
        ),
        // The Swift API: the generated bindings.
        .target(
            name: "Tonekit",
            dependencies: ["TonekitFFI"],
            path: "Sources/Tonekit",
            linkerSettings: [
                // What a Rust static library needs from the platform (rustc's
                // `--print native-static-libs`, which build-xcframework.sh prints).
                .linkedLibrary("iconv"),
                .linkedFramework("Security"),
                .linkedFramework("Foundation"),
            ]
        ),
        .testTarget(
            name: "TonekitSmokeTests",
            dependencies: ["Tonekit"],
            resources: [.copy("Resources")]
        ),
    ]
)
