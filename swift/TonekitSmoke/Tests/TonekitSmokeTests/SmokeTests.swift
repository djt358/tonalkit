// Task 12: the Rust library called from Swift through the UniFFI bindings, on the iOS Simulator.
//
// The main test grades the shared fixture recording (`fixtures/spoken-413.wav`, the syllables
// 4-1-3 spoken by the synthetic voice) and compares the result with `tonekit assess --json` on
// the same file (`fixtures/spoken-413.assessment.json`). The Rust tests hold the same numbers.
// Comparisons are within 1e-4 (ruling R41): another platform's libm may move the last bits.
//
// The fixture pair and the pack are test resources that scripts/build-xcframework.sh copies from
// fixtures/ and packs/cmn/. The package needs the Resources/ directory to exist in order to
// compile (`resources: [.copy("Resources")]`), and it is git-ignored, so it is there only after
// that script has run. The `#filePath` fallback below helps only when that directory exists but a
// single file is missing from the bundle: the tests then read the repository copy next to this
// source file.

import AVFoundation
import Foundation
import XCTest

import Tonekit

final class SmokeTests: XCTestCase {
    /// Absolute tolerance against the checked-in CLI output (R41).
    private let tolerance = 1e-4

    // MARK: The fixture, end to end

    func testSpokenFixtureMatchesCli() throws {
        let pcm = try Fixtures.pcm()
        let pack = try Fixtures.pack()
        let expected = try Fixtures.expectedAssessment()

        let analysis = try analyze(pcm: pcm, sampleRate: 16_000, register: nil, externalF0: nil)
        let assessment = try assess(analysis: analysis, pack: pack, request: Fixtures.request413())

        XCTAssertEqual(assessment.schema, "tonekit.assessment.v1")
        XCTAssertEqual(assessment.intended, expected.intended)
        XCTAssertEqual(assessment.intendedRank, 1)
        XCTAssertEqual(Int(assessment.intendedRank), expected.intendedRank)
        XCTAssertEqual(Double(assessment.marginLlr), expected.marginLlr, accuracy: tolerance)

        let wantOverall = try XCTUnwrap(expected.overall)
        let gotOverall = try XCTUnwrap(assessment.overall)
        XCTAssertEqual(Double(gotOverall), wantOverall, accuracy: tolerance)

        XCTAssertEqual(assessment.syllables.count, 3)
        XCTAssertEqual(assessment.syllables.count, expected.syllables.count)
        for (index, want) in expected.syllables.enumerated() where index < assessment.syllables.count {
            let got = assessment.syllables[index]
            XCTAssertEqual(got.expected, want.expected, "syllable \(index)")
            XCTAssertEqual(Double(got.pCorrect), want.pCorrect, accuracy: tolerance, "syllable \(index) pCorrect")
            XCTAssertEqual(got.heard, want.heard, "syllable \(index) heard")
            XCTAssertEqual(got.distance == nil, want.distance == nil, "syllable \(index) distance presence")
            if let gotDistance = got.distance, let wantDistance = want.distance {
                XCTAssertEqual(Double(gotDistance), wantDistance, accuracy: tolerance, "syllable \(index) distance")
            }
            // A cold start: every syllable is at best partial, flagged with the register issue.
            XCTAssertEqual(got.measured, Measured.partial(issues: [MeasureIssue.coldStartRegister]), "syllable \(index)")
        }
        XCTAssertEqual(assessment.registerUpdate.nSyllables, 3)
    }

    // MARK: Latency (informational in P0; the gate is p95 on a physical iPhone 12, in P1)

    func testAssessLatency() throws {
        let pcm = try Fixtures.pcm()
        let pack = try Fixtures.pack()
        let request = Fixtures.request413()
        let audioMilliseconds = Double(pcm.count) / 16.0

        // One untimed run first: a broken build fails here instead of reading as a fast time.
        let warmup = try assess(
            analysis: try analyze(pcm: pcm, sampleRate: 16_000, register: nil, externalF0: nil),
            pack: pack,
            request: request
        )
        XCTAssertEqual(warmup.intendedRank, 1)

        // XCTest's measurement: ten runs, reported in the xcodebuild log as
        // "measured [Time, seconds] average: ...".
        measure {
            do {
                let analysis = try analyze(pcm: pcm, sampleRate: 16_000, register: nil, externalF0: nil)
                _ = try assess(analysis: analysis, pack: pack, request: request)
            } catch {
                XCTFail("analyze + assess threw: \(error)")
            }
        }

        // The same thing as plain numbers, for the report back.
        var milliseconds: [Double] = []
        for _ in 0..<20 {
            let start = DispatchTime.now().uptimeNanoseconds
            let analysis = try analyze(pcm: pcm, sampleRate: 16_000, register: nil, externalF0: nil)
            _ = try assess(analysis: analysis, pack: pack, request: request)
            let end = DispatchTime.now().uptimeNanoseconds
            milliseconds.append(Double(end - start) / 1_000_000.0)
        }
        milliseconds.sort()
        let median = milliseconds[milliseconds.count / 2]
        let p95 = milliseconds[Int(Double(milliseconds.count - 1) * 0.95)]
        print(String(
            format: "TONEKIT_LATENCY audio_ms=%.0f analyze_plus_assess_median_ms=%.1f p95_ms=%.1f runs=%ld",
            audioMilliseconds, median, p95, milliseconds.count
        ))
    }

    // MARK: The API surface

    func testPackReportsItsLectBaseAccentAndInventory() throws {
        let pack = try Fixtures.pack()
        XCTAssertEqual(pack.lect(), "cmn")
        XCTAssertEqual(pack.baseAccent(), "cmn-standard")
        XCTAssertEqual(pack.inventory(), ["1", "2", "3", "4", "5"])
    }

    func testTheCalibrationIsOptional() throws {
        let toml = try Fixtures.text("cmn", "toml", repoPath: "packs/cmn/cmn.toml")
        let pack = try Pack.fromToml(packToml: toml, calibJson: nil)
        XCTAssertEqual(pack.lect(), "cmn")
    }

    func testABadPackThrowsAPackError() {
        XCTAssertThrowsError(try Pack.fromToml(packToml: "this is [not toml", calibJson: nil)) { error in
            guard let assessError = error as? AssessError, case .Pack(let message) = assessError else {
                XCTFail("expected AssessError.Pack, got \(error)")
                return
            }
            XCTAssertTrue(message.contains("pack parse error"), message)
        }
    }

    func testAnalyzeRejectsWhatTheRustSideRejects() {
        XCTAssertThrowsError(try analyze(pcm: [], sampleRate: 16_000, register: nil, externalF0: nil)) { error in
            XCTAssertEqual(error as? AssessError, AssessError.EmptyAudio)
        }
        let silence = [Float](repeating: 0, count: 4_410)
        XCTAssertThrowsError(try analyze(pcm: silence, sampleRate: 44_100, register: nil, externalF0: nil)) { error in
            XCTAssertEqual(error as? AssessError, AssessError.UnsupportedSampleRate(got: 44_100))
        }
    }

    func testAnUnknownToneThrows() throws {
        let analysis = try analyze(pcm: try Fixtures.pcm(), sampleRate: 16_000, register: nil, externalF0: nil)
        let pack = try Fixtures.pack()
        let request = AssessRequest(
            grading: GradingTarget(accent: "cmn-standard", style: nil, styleWeight: 0),
            intended: Fixtures.candidate(id: "intended", tones: ["4", "9", "3"])
        )
        XCTAssertThrowsError(try assess(analysis: analysis, pack: pack, request: request)) { error in
            XCTAssertEqual(error as? AssessError, AssessError.UnknownTone(tone: "9"))
        }
    }

    func testDecodeAndLatticeAreExported() throws {
        let analysis = try analyze(pcm: try Fixtures.pcm(), sampleRate: 16_000, register: nil, externalF0: nil)
        let pack = try Fixtures.pack()
        let grading = GradingTarget(accent: "cmn-standard", style: nil, styleWeight: 0)

        let decoded = try decode(
            analysis: analysis,
            pack: pack,
            grading: grading,
            candidates: [
                Fixtures.candidate(id: "right", tones: ["4", "1", "3"]),
                Fixtures.candidate(id: "wrong", tones: ["1", "4", "2"]),
            ]
        )
        XCTAssertEqual(decoded.candidates.count, 2)
        XCTAssertEqual(decoded.candidates[0].id, "right")

        let openSet = try lattice(analysis: analysis, pack: pack, grading: grading)
        XCTAssertEqual(openSet.schema, "tonekit.lattice.v1")
        XCTAssertEqual(openSet.lect, "cmn")
        XCTAssertEqual(openSet.inventory.count, 5)
        XCTAssertEqual(openSet.tbus.count, 3)
    }

    // MARK: A pitch track from outside

    func testAnExternalF0TrackIsUsedAndSanitised() throws {
        let pcm = try Fixtures.pcm()
        let pack = try Fixtures.pack()
        let pyin = try analyze(pcm: pcm, sampleRate: 16_000, register: nil, externalF0: nil)
        XCTAssertEqual(pyin.f0.provider, "pyin")

        // pYIN's own track handed back as if a neural pitch model had produced it.
        let borrowed = F0Track(frames: pyin.f0.frames, provider: "somebody-else")
        let external = try analyze(pcm: pcm, sampleRate: 16_000, register: nil, externalF0: borrowed)
        XCTAssertEqual(external.f0.provider, "external")
        XCTAssertEqual(external.f0.frames.count, pyin.f0.frames.count)

        // Any floats may cross the boundary (ruling R43): NaN, negative and infinite Hz, NaN and
        // out-of-range confidences. None of it may reach the assessment.
        var frames = pyin.f0.frames
        let voiced = frames.indices.filter { frames[$0].hz != nil }
        XCTAssertGreaterThan(voiced.count, 40)
        frames[voiced[5]].hz = Float.nan
        frames[voiced[10]].hz = -5
        frames[voiced[15]].hz = Float.infinity
        frames[voiced[20]].voicedP = Float.nan
        frames[voiced[25]].voicedP = 42
        let hostile = F0Track(frames: frames, provider: "hostile")
        let sanitised = try analyze(pcm: pcm, sampleRate: 16_000, register: nil, externalF0: hostile)
        for frame in sanitised.f0.frames {
            if let hz = frame.hz {
                XCTAssertTrue(hz.isFinite && hz > 0, "hz \(hz)")
            }
            XCTAssertTrue(frame.voicedP >= 0 && frame.voicedP <= 1, "voicedP \(frame.voicedP)")
        }
        let assessment = try assess(analysis: sanitised, pack: pack, request: Fixtures.request413())
        let overall = try XCTUnwrap(assessment.overall)
        XCTAssertTrue(overall.isFinite)
        XCTAssertTrue(assessment.marginLlr.isFinite)
        for syllable in assessment.syllables {
            XCTAssertTrue(syllable.pCorrect.isFinite)
        }
    }

    // MARK: Loading the audio

    /// AVAudioFile reads the fixture (WAVE_FORMAT_EXTENSIBLE, float32, 16 kHz mono) to the same
    /// samples as a plain RIFF parse. The other tests fall back to the parser if AVAudioFile fails.
    func testAVAudioFileReadsTheFixture() throws {
        let url = try Fixtures.url("spoken-413", "wav", repoPath: "fixtures/spoken-413.wav")
        let viaAVAudioFile = try Fixtures.samplesViaAVAudioFile(url)
        let viaParser = try RiffFloatWav.samples(of: Data(contentsOf: url))
        XCTAssertEqual(viaAVAudioFile.count, viaParser.count)
        XCTAssertGreaterThan(viaParser.count, 16_000)
        var largest: Float = 0
        for (a, b) in zip(viaAVAudioFile, viaParser) {
            largest = max(largest, abs(a - b))
        }
        XCTAssertLessThan(largest, 1e-6)
    }
}

// MARK: - Fixtures

private enum FixtureError: Error, CustomStringConvertible {
    case missing(String)
    case unreadable(String)

    var description: String {
        switch self {
        case .missing(let what):
            return "missing test resource \(what): run scripts/build-xcframework.sh, which copies it into the package"
        case .unreadable(let what):
            return "cannot read \(what)"
        }
    }
}

/// The subset of `spoken-413.assessment.json` (`tonekit assess --json`) that the tests compare.
/// The file's keys are snake_case; the decoder converts them.
private struct ExpectedAssessment: Decodable {
    struct Syllable: Decodable {
        let expected: String
        let pCorrect: Double
        let distance: Double?
        let heard: String?
    }

    let intended: String
    let intendedRank: Int
    let marginLlr: Double
    let overall: Double?
    let syllables: [Syllable]
}

private enum Fixtures {
    /// A test resource: from the bundle, else from the repository copy at `repoPath`.
    static func url(_ name: String, _ ext: String, repoPath: String, file: StaticString = #filePath) throws -> URL {
        if let bundled = Bundle.module.url(forResource: name, withExtension: ext, subdirectory: "Resources") {
            return bundled
        }
        // .../swift/TonekitSmoke/Tests/TonekitSmokeTests/SmokeTests.swift -> the repository root.
        var root = URL(fileURLWithPath: "\(file)")
        for _ in 0..<5 {
            root.deleteLastPathComponent()
        }
        let fallback = root.appendingPathComponent(repoPath)
        guard FileManager.default.fileExists(atPath: fallback.path) else {
            throw FixtureError.missing("\(name).\(ext)")
        }
        return fallback
    }

    static func text(_ name: String, _ ext: String, repoPath: String) throws -> String {
        let location = try url(name, ext, repoPath: repoPath)
        return try String(contentsOf: location, encoding: .utf8)
    }

    /// The fixture recording as floats in -1...1, 16 kHz mono.
    static func pcm() throws -> [Float] {
        let location = try url("spoken-413", "wav", repoPath: "fixtures/spoken-413.wav")
        do {
            return try samplesViaAVAudioFile(location)
        } catch {
            print("AVAudioFile could not read \(location.lastPathComponent) (\(error)); using the RIFF parser")
            return try RiffFloatWav.samples(of: Data(contentsOf: location))
        }
    }

    static func samplesViaAVAudioFile(_ location: URL) throws -> [Float] {
        let file = try AVAudioFile(forReading: location)
        let format = file.processingFormat
        guard format.sampleRate == 16_000, format.channelCount == 1 else {
            throw FixtureError.unreadable("\(location.lastPathComponent): expected 16 kHz mono, got \(format)")
        }
        let capacity = AVAudioFrameCount(file.length)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else {
            throw FixtureError.unreadable("\(location.lastPathComponent): no buffer of \(capacity) frames")
        }
        try file.read(into: buffer)
        guard let channels = buffer.floatChannelData else {
            throw FixtureError.unreadable("\(location.lastPathComponent): not float samples")
        }
        let first: UnsafePointer<Float> = UnsafePointer(channels[0])
        return Array(UnsafeBufferPointer(start: first, count: Int(buffer.frameLength)))
    }

    /// The bundled cmn pack with its calibration.
    static func pack() throws -> Pack {
        let toml = try text("cmn", "toml", repoPath: "packs/cmn/cmn.toml")
        let calibration = try text("cmn.calib", "json", repoPath: "packs/cmn/cmn.calib.json")
        return try Pack.fromToml(packToml: toml, calibJson: calibration)
    }

    static func expectedAssessment() throws -> ExpectedAssessment {
        let location = try url("spoken-413.assessment", "json", repoPath: "fixtures/spoken-413.assessment.json")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(ExpectedAssessment.self, from: Data(contentsOf: location))
    }

    /// A candidate reading with no lexical variants or labels.
    static func candidate(id: String, tones: [String]) -> Candidate {
        var targets: [ToneTarget] = []
        for tone in tones {
            targets.append(ToneTarget(tone: tone, lexicalVariants: [], label: nil))
        }
        return Candidate(id: id, targets: targets)
    }

    /// What `tonekit assess --tones "4 1 3" --labels "yi bei shui"` grades: the standard accent,
    /// no imprint, no distractors, no external evidence, intended id "intended".
    static func request413() -> AssessRequest {
        let tones = ["4", "1", "3"]
        let labels = ["yi", "bei", "shui"]
        var targets: [ToneTarget] = []
        for index in 0..<tones.count {
            targets.append(ToneTarget(tone: tones[index], lexicalVariants: [], label: labels[index]))
        }
        return AssessRequest(
            grading: GradingTarget(accent: "cmn-standard", style: nil, styleWeight: 0),
            intended: Candidate(id: "intended", targets: targets)
        )
    }
}

// MARK: - A plain RIFF reader

/// Reads the samples of a 16 kHz mono float32 WAV (plain, or WAVE_FORMAT_EXTENSIBLE with the
/// IEEE-float sub-format) without any Apple audio framework.
private enum RiffFloatWav {
    static func samples(of data: Data) throws -> [Float] {
        let bytes = [UInt8](data)

        func u16(_ offset: Int) -> Int {
            return Int(bytes[offset]) | (Int(bytes[offset + 1]) << 8)
        }
        func u32(_ offset: Int) -> Int {
            return u16(offset) | (u16(offset + 2) << 16)
        }
        func tag(_ offset: Int) -> String {
            return String(bytes: bytes[offset..<(offset + 4)], encoding: .ascii) ?? ""
        }

        guard bytes.count >= 12, tag(0) == "RIFF", tag(8) == "WAVE" else {
            throw FixtureError.unreadable("not a RIFF/WAVE file")
        }
        var offset = 12
        var sawFormat = false
        while offset + 8 <= bytes.count {
            let chunk = tag(offset)
            let size = u32(offset + 4)
            let body = offset + 8
            if chunk == "fmt " {
                var formatTag = u16(body)
                let channels = u16(body + 2)
                let rate = u32(body + 4)
                let bits = u16(body + 14)
                if formatTag == 0xFFFE {
                    // WAVE_FORMAT_EXTENSIBLE: the real format is the first two bytes of the
                    // sub-format GUID, at offset 24 of the chunk.
                    formatTag = u16(body + 24)
                }
                guard formatTag == 3, bits == 32, channels == 1, rate == 16_000 else {
                    throw FixtureError.unreadable("expected 16 kHz mono float32, got tag \(formatTag), \(bits) bits, \(channels) channels, \(rate) Hz")
                }
                sawFormat = true
            } else if chunk == "data" {
                guard sawFormat else {
                    throw FixtureError.unreadable("data chunk before fmt chunk")
                }
                let end = min(body + size, bytes.count)
                let count = (end - body) / 4
                var samples: [Float] = []
                samples.reserveCapacity(count)
                for index in 0..<count {
                    let at = body + 4 * index
                    var word: UInt32 = UInt32(bytes[at])
                    word |= UInt32(bytes[at + 1]) << 8
                    word |= UInt32(bytes[at + 2]) << 16
                    word |= UInt32(bytes[at + 3]) << 24
                    samples.append(Float(bitPattern: word))
                }
                return samples
            }
            offset = body + size + (size & 1)
        }
        throw FixtureError.unreadable("no data chunk")
    }
}
