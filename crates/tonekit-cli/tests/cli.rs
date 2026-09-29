//! The `tonekit` binary end to end: synthetic 4-1-3 speech on disk in, assessment out.
//!
//! The same 4-1-3 recording is the shared fixture `fixtures/spoken-413.wav` (with its expected
//! `spoken-413.assessment.json`) that the Swift and Python bindings must reproduce. Update the
//! checked-in pair on purpose with `UPDATE_FIXTURES=1 cargo test -p tonekit-cli`.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use tempfile::TempDir;
use tonekit::{MeasureIssue, Measured, ToneLattice, UtteranceAssessment};
use tonekit_testkit::{synth, SynthSpec, SynthSyllable};

const PACK: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../packs/cmn/cmn.toml");
const CALIB: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../packs/cmn/cmn.calib.json"
);
const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../fixtures");

const RESAMPLE_HINT: &str = "resample with `tkh ingest`";

/// Ruling R8's spoken tones 4, 1 and (phrase-final) 3; 250 ms syllables, 60 ms gaps, floor
/// 100 Hz / ceiling 200 Hz, 200 ms lead and tail, seed 1.
fn spoken_413() -> Vec<f32> {
    let syllable = |chao: &[f32]| SynthSyllable {
        chao: chao.to_vec(),
        dur_ms: 250.0,
        gap_after_ms: 60.0,
        unvoiced_onset_ms: 0.0,
        creak: None,
    };
    synth(&SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: vec![
            syllable(&[5.0, 1.0]),
            syllable(&[5.0, 5.0]),
            syllable(&[2.0, 1.0, 4.0]),
        ],
        snr_db: None,
        seed: 1,
    })
    .pcm
}

fn wav_spec(
    channels: u16,
    sample_rate: u32,
    bits: u16,
    format: hound::SampleFormat,
) -> hound::WavSpec {
    hound::WavSpec {
        channels,
        sample_rate,
        bits_per_sample: bits,
        sample_format: format,
    }
}

/// `pcm` as a mono 32-bit float WAV at `sample_rate`.
fn write_f32_wav(path: &Path, sample_rate: u32, pcm: &[f32]) {
    let spec = wav_spec(1, sample_rate, 32, hound::SampleFormat::Float);
    let mut writer = hound::WavWriter::create(path, spec).unwrap();
    for &x in pcm {
        writer.write_sample(x).unwrap();
    }
    writer.finalize().unwrap();
}

/// `pcm` as a 16 kHz mono PCM16 WAV.
fn write_i16_wav(path: &Path, pcm: &[f32]) {
    let spec = wav_spec(1, 16_000, 16, hound::SampleFormat::Int);
    let mut writer = hound::WavWriter::create(path, spec).unwrap();
    for &x in pcm {
        writer.write_sample((x * 32767.0).round() as i16).unwrap();
    }
    writer.finalize().unwrap();
}

fn tonekit(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_tonekit"))
        .args(args)
        .output()
        .unwrap()
}

fn path_str(path: &Path) -> &str {
    path.to_str().unwrap()
}

/// `tonekit assess <wav> --pack <PACK> --tones "4 1 3" --labels "yi bei shui" <extra>`.
fn assess(wav: &Path, extra: &[&str]) -> Output {
    let mut args = vec![
        "assess",
        path_str(wav),
        "--pack",
        PACK,
        "--tones",
        "4 1 3",
        "--labels",
        "yi bei shui",
    ];
    args.extend_from_slice(extra);
    tonekit(&args)
}

fn stdout(out: &Output) -> String {
    String::from_utf8(out.stdout.clone()).unwrap()
}

fn stderr(out: &Output) -> String {
    String::from_utf8(out.stderr.clone()).unwrap()
}

fn parsed(out: &Output) -> UtteranceAssessment {
    serde_json::from_slice(&out.stdout).unwrap_or_else(|e| {
        panic!(
            "stdout is not an UtteranceAssessment ({e}):\n{}\nstderr:\n{}",
            stdout(out),
            stderr(out)
        )
    })
}

/// A temp dir holding the spoken 4-1-3 as a float WAV.
fn fixture_dir() -> (TempDir, PathBuf) {
    let dir = TempDir::new().unwrap();
    let wav = dir.path().join("spoken-413.wav");
    write_f32_wav(&wav, 16_000, &spoken_413());
    (dir, wav)
}

#[test]
fn assess_json_grades_the_synthetic_413() {
    let (_dir, wav) = fixture_dir();
    let out = assess(&wav, &["--json"]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    assert_eq!(stderr(&out), "");
    let assessment = parsed(&out);
    assert_eq!(assessment.schema, "tonekit.assessment.v1");
    assert_eq!(assessment.intended.0, "intended");
    assert_eq!(assessment.syllables.len(), 3);
    let expected: Vec<_> = assessment
        .syllables
        .iter()
        .map(|s| &*s.expected.0)
        .collect();
    assert_eq!(expected, ["4", "1", "3"]);
    assert!(assessment.overall.is_some());
    assert!(assessment.accent_fit.is_empty());
}

#[test]
fn json_output_is_only_the_pretty_printed_assessment() {
    let (_dir, wav) = fixture_dir();
    let out = assess(&wav, &["--json"]);
    let text = stdout(&out);
    let again = serde_json::to_string_pretty(&parsed(&out)).unwrap();
    assert_eq!(text, format!("{again}\n"));
}

#[test]
fn pcm16_wav_is_accepted() {
    let dir = TempDir::new().unwrap();
    let wav = dir.path().join("pcm16.wav");
    write_i16_wav(&wav, &spoken_413());
    let out = assess(&wav, &["--json"]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    assert_eq!(parsed(&out).syllables.len(), 3);
}

#[test]
fn wav_at_44100_hz_exits_2_with_a_resample_hint() {
    let dir = TempDir::new().unwrap();
    let wav = dir.path().join("cd-rate.wav");
    write_f32_wav(&wav, 44_100, &spoken_413());
    let out = assess(&wav, &["--json"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(stderr(&out).contains(RESAMPLE_HINT), "{}", stderr(&out));
    assert!(stderr(&out).contains("44100"), "{}", stderr(&out));
    assert_eq!(stdout(&out), "");
}

#[test]
fn lattice_also_rejects_the_wrong_sample_rate() {
    let dir = TempDir::new().unwrap();
    let wav = dir.path().join("cd-rate.wav");
    write_f32_wav(&wav, 44_100, &spoken_413());
    let out = tonekit(&["lattice", path_str(&wav), "--pack", PACK]);
    assert_eq!(out.status.code(), Some(2));
    assert!(stderr(&out).contains(RESAMPLE_HINT), "{}", stderr(&out));
}

#[test]
fn stereo_and_24_bit_wavs_exit_2_with_the_hint() {
    let dir = TempDir::new().unwrap();

    let stereo = dir.path().join("stereo.wav");
    let mut writer =
        hound::WavWriter::create(&stereo, wav_spec(2, 16_000, 32, hound::SampleFormat::Float))
            .unwrap();
    for x in spoken_413() {
        writer.write_sample(x).unwrap();
        writer.write_sample(x).unwrap();
    }
    writer.finalize().unwrap();

    let deep = dir.path().join("pcm24.wav");
    let mut writer =
        hound::WavWriter::create(&deep, wav_spec(1, 16_000, 24, hound::SampleFormat::Int)).unwrap();
    for x in spoken_413() {
        writer.write_sample((x * 8_388_607.0) as i32).unwrap();
    }
    writer.finalize().unwrap();

    for wav in [&stereo, &deep] {
        let out = assess(wav, &["--json"]);
        assert_eq!(out.status.code(), Some(2), "{}", wav.display());
        assert!(stderr(&out).contains(RESAMPLE_HINT), "{}", stderr(&out));
    }
}

#[test]
fn labels_that_do_not_match_the_tones_exit_2() {
    let (_dir, wav) = fixture_dir();
    let out = tonekit(&[
        "assess",
        path_str(&wav),
        "--pack",
        PACK,
        "--tones",
        "4 1 3",
        "--labels",
        "yi bei",
    ]);
    assert_eq!(out.status.code(), Some(2));
    assert!(stderr(&out).contains("--labels"), "{}", stderr(&out));
    assert_eq!(stdout(&out), "");
}

#[test]
fn an_empty_tone_list_exits_2() {
    let (_dir, wav) = fixture_dir();
    let out = tonekit(&["assess", path_str(&wav), "--pack", PACK, "--tones", " "]);
    assert_eq!(out.status.code(), Some(2));
    assert!(stderr(&out).contains("--tones"), "{}", stderr(&out));
}

#[test]
fn a_missing_required_flag_exits_2() {
    let (_dir, wav) = fixture_dir();
    let out = tonekit(&["assess", path_str(&wav), "--pack", PACK]);
    assert_eq!(out.status.code(), Some(2));
}

#[test]
fn unreadable_inputs_exit_1_with_the_reason_on_stderr() {
    let dir = TempDir::new().unwrap();
    let missing = dir.path().join("nope.wav");
    let out = assess(&missing, &["--json"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains("nope.wav"), "{}", stderr(&out));

    let junk = dir.path().join("junk.wav");
    fs::write(&junk, b"this is not a WAV file").unwrap();
    let out = assess(&junk, &["--json"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains("junk.wav"), "{}", stderr(&out));

    let (_wav_dir, wav) = fixture_dir();
    let out = tonekit(&[
        "assess",
        path_str(&wav),
        "--pack",
        path_str(&dir.path().join("no-such-pack.toml")),
        "--tones",
        "4 1 3",
    ]);
    assert_eq!(out.status.code(), Some(1));
    assert!(
        stderr(&out).contains("no-such-pack.toml"),
        "{}",
        stderr(&out)
    );

    let broken = dir.path().join("broken.toml");
    fs::write(&broken, "[pack\nlect = ").unwrap();
    let out = tonekit(&[
        "assess",
        path_str(&wav),
        "--pack",
        path_str(&broken),
        "--tones",
        "4 1 3",
    ]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains("pack"), "{}", stderr(&out));
}

#[test]
fn an_empty_wav_exits_1() {
    let dir = TempDir::new().unwrap();
    let wav = dir.path().join("empty.wav");
    write_f32_wav(&wav, 16_000, &[]);
    let out = assess(&wav, &["--json"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains("empty"), "{}", stderr(&out));
}

#[test]
fn unknown_accents_and_tones_exit_1_naming_the_culprit() {
    let (_dir, wav) = fixture_dir();

    let out = assess(&wav, &["--accent", "cmn-XX"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains("cmn-XX"), "{}", stderr(&out));

    let out = assess(&wav, &["--compare-accent", "cmn-YY"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains("cmn-YY"), "{}", stderr(&out));

    let out = tonekit(&[
        "lattice",
        path_str(&wav),
        "--pack",
        PACK,
        "--accent",
        "cmn-ZZ",
    ]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains("cmn-ZZ"), "{}", stderr(&out));

    let out = tonekit(&["assess", path_str(&wav), "--pack", PACK, "--tones", "4 9 3"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains('9'), "{}", stderr(&out));
    assert_eq!(stdout(&out), "");
}

#[test]
fn the_table_has_a_row_per_syllable_and_ends_with_overall_and_margin() {
    let (_dir, wav) = fixture_dir();
    let out = assess(&wav, &[]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    let text = stdout(&out);
    let lines: Vec<&str> = text.lines().collect();

    let header: Vec<&str> = lines[0].split_whitespace().collect();
    assert_eq!(
        header,
        [
            "label",
            "expected",
            "heard",
            "p_correct",
            "distance",
            "component",
            "deltas"
        ]
    );
    for (row, (label, tone)) in lines[1..4]
        .iter()
        .zip([("yi", "4"), ("bei", "1"), ("shui", "3")])
    {
        let cells: Vec<&str> = row.split_whitespace().collect();
        assert_eq!(&cells[..2], [label, tone], "{row}");
    }
    let last = lines.last().unwrap();
    assert!(last.starts_with("overall "), "{last}");
    assert!(last.contains("margin "), "{last}");
    assert!(!text.contains("NaN") && !text.contains("null"), "{text}");
}

#[test]
fn unlabelled_syllables_are_numbered_in_the_table() {
    let (_dir, wav) = fixture_dir();
    let out = tonekit(&["assess", path_str(&wav), "--pack", PACK, "--tones", "4 1 3"]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    let text = stdout(&out);
    let firsts: Vec<&str> = text
        .lines()
        .skip(1)
        .take(3)
        .map(|l| l.split_whitespace().next().unwrap())
        .collect();
    assert_eq!(firsts, ["s1", "s2", "s3"]);
}

#[test]
fn silence_is_reported_as_not_measured_and_not_checked() {
    let dir = TempDir::new().unwrap();
    let wav = dir.path().join("silence.wav");
    write_f32_wav(&wav, 16_000, &[0.0; 16_000]);

    let out = assess(&wav, &[]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    let text = stdout(&out);
    let lines: Vec<&str> = text.lines().collect();
    assert_eq!(lines.len(), 1 + 3 + 3 + 1, "{text}");
    for (line, label) in lines[4..7].iter().zip(["yi", "bei", "shui"]) {
        assert!(
            line.starts_with(&format!("{label}: not measured (")),
            "{line}"
        );
    }
    assert!(lines[7].starts_with("overall not checked "), "{}", lines[7]);

    let out = tonekit(&["lattice", path_str(&wav), "--pack", PACK]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    assert!(
        stdout(&out).ends_with("no syllable nuclei found\n"),
        "{}",
        stdout(&out)
    );
}

#[test]
fn distractors_compete_with_the_intended_reading() {
    let (_dir, wav) = fixture_dir();

    // The audio says 4-1-3, so 1-1-1 intended with 4-1-3 as a distractor ranks second and has a
    // negative margin; with no distractor it is rank 1.
    let args = |extra: &[&str]| {
        let mut all = vec![
            "assess",
            path_str(&wav),
            "--pack",
            PACK,
            "--tones",
            "1 1 1",
            "--json",
        ];
        all.extend_from_slice(extra);
        tonekit(&all)
    };
    let alone = parsed(&args(&[]));
    assert_eq!(alone.intended_rank, 1);
    let out = args(&["--distractor", "4 1 3", "--distractor", "2 2 2"]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    let contested = parsed(&out);
    assert_eq!(contested.intended_rank, 3);
    assert!(contested.margin_llr < 0.0, "{}", contested.margin_llr);
    assert!(contested.margin_llr < alone.margin_llr);
}

#[test]
fn compare_accents_report_a_fit_each_in_the_order_given() {
    let (_dir, wav) = fixture_dir();
    let out = assess(
        &wav,
        &[
            "--compare-accent",
            "cmn-TW",
            "--compare-accent",
            "cmn-standard",
            "--json",
        ],
    );
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    let fits = parsed(&out).accent_fit;
    let accents: Vec<_> = fits.iter().map(|f| &*f.accent.0).collect();
    assert_eq!(accents, ["cmn-TW", "cmn-standard"]);
}

#[test]
fn the_accent_flag_selects_the_grading_accent() {
    let (_dir, wav) = fixture_dir();
    let base = |extra: &[&str]| {
        let mut all = vec!["lattice", path_str(&wav), "--pack", PACK, "--json"];
        all.extend_from_slice(extra);
        let out = tonekit(&all);
        assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
        serde_json::from_slice::<ToneLattice>(&out.stdout).unwrap()
    };
    assert_eq!(base(&[]).accent.0, "cmn-standard");
    assert_eq!(base(&["--accent", "cmn-TW"]).accent.0, "cmn-TW");
}

#[test]
fn lattice_json_has_one_tbu_per_syllable() {
    let (_dir, wav) = fixture_dir();
    let out = tonekit(&["lattice", path_str(&wav), "--pack", PACK, "--json"]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    assert_eq!(stderr(&out), "");
    let lattice: ToneLattice = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(
        stdout(&out),
        format!("{}\n", serde_json::to_string_pretty(&lattice).unwrap())
    );
    assert_eq!(lattice.schema, "tonekit.lattice.v1");
    assert_eq!(lattice.lect.0, "cmn");
    assert_eq!(lattice.inventory.len(), 5);
    assert_eq!(lattice.tbus.len(), 3);
    for tbu in &lattice.tbus {
        assert_eq!(tbu.posterior.len(), 5);
        assert!(!matches!(tbu.measured, Measured::NotMeasured { .. }));
    }
}

#[test]
fn lattice_table_has_a_row_per_tbu() {
    let (_dir, wav) = fixture_dir();
    let out = tonekit(&["lattice", path_str(&wav), "--pack", PACK]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    let text = stdout(&out);
    let lines: Vec<&str> = text.lines().collect();
    assert_eq!(lines.len(), 4, "{text}");
    let header: Vec<&str> = lines[0].split_whitespace().collect();
    assert_eq!(&header[..3], ["tbu", "span_ms", "best"]);
    // The synthetic speech is 4, 1, then 3: each best tone leads its own row.
    let best: Vec<&str> = lines[1..]
        .iter()
        .map(|l| l.split_whitespace().nth(2).unwrap())
        .collect();
    assert_eq!(best, ["4", "1", "3"], "{text}");
}

#[test]
fn a_sibling_calibration_file_is_used_when_calib_is_omitted() {
    let dir = TempDir::new().unwrap();
    let (_wav_dir, wav) = fixture_dir();
    let pack_toml = fs::read_to_string(PACK).unwrap();
    let calib = fs::read_to_string(CALIB).unwrap();
    let sharper = calib.replace("\"temperature\": 1.0", "\"temperature\": 2.5");
    assert_ne!(sharper, calib);

    let plain = dir.path().join("plain");
    let tuned = dir.path().join("tuned");
    fs::create_dir_all(&plain).unwrap();
    fs::create_dir_all(&tuned).unwrap();
    fs::write(plain.join("cmn.toml"), &pack_toml).unwrap();
    fs::write(tuned.join("cmn.toml"), &pack_toml).unwrap();
    fs::write(tuned.join("cmn.calib.json"), &sharper).unwrap();
    fs::write(dir.path().join("sharper.json"), &sharper).unwrap();

    let run = |pack: &Path, extra: &[&str]| {
        let mut args = vec![
            "assess",
            path_str(&wav),
            "--pack",
            path_str(pack),
            "--tones",
            "4 1 3",
            "--json",
        ];
        args.extend_from_slice(extra);
        let out = tonekit(&args);
        assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
        stdout(&out)
    };
    let seeded = run(&plain.join("cmn.toml"), &[]);
    let sibling = run(&tuned.join("cmn.toml"), &[]);
    let explicit = run(
        &plain.join("cmn.toml"),
        &["--calib", path_str(&dir.path().join("sharper.json"))],
    );
    assert_ne!(seeded, sibling, "the sibling calibration was ignored");
    assert_eq!(sibling, explicit);

    // The shipped pack's own sibling is the shipped calibration.
    assert_eq!(
        run(Path::new(PACK), &[]),
        run(Path::new(PACK), &["--calib", CALIB])
    );

    // An explicit calibration that is missing is an error, not a silent fallback.
    let missing = dir.path().join("missing.json");
    let out = tonekit(&[
        "assess",
        path_str(&wav),
        "--pack",
        PACK,
        "--tones",
        "4 1 3",
        "--calib",
        path_str(&missing),
    ]);
    assert_eq!(out.status.code(), Some(1));
    assert!(stderr(&out).contains("missing.json"), "{}", stderr(&out));
}

/// Regenerates the shared fixture pair in a temp dir and requires the checked-in copies to match.
///
/// `fixtures/spoken-413.assessment.json` is `tonekit assess --json` on `fixtures/spoken-413.wav`
/// with `--pack packs/cmn/cmn.toml --tones "4 1 3" --labels "yi bei shui"`. Swift and Python
/// reproduce it exactly, so it must not drift unnoticed: rewrite both on purpose with
/// `UPDATE_FIXTURES=1`.
#[test]
fn checked_in_fixtures_match_a_fresh_run() {
    let (dir, wav) = fixture_dir();
    let out = assess(&wav, &["--json"]);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    let json = dir.path().join("spoken-413.assessment.json");
    fs::write(&json, &out.stdout).unwrap();

    let checked_in = Path::new(FIXTURES);
    let updating = std::env::var("UPDATE_FIXTURES").is_ok_and(|v| v == "1");
    if updating {
        fs::create_dir_all(checked_in).unwrap();
        fs::copy(&wav, checked_in.join("spoken-413.wav")).unwrap();
        fs::copy(&json, checked_in.join("spoken-413.assessment.json")).unwrap();
    }

    let hint = "run `UPDATE_FIXTURES=1 cargo test -p tonekit-cli` to update them on purpose";
    let old_wav = fs::read(checked_in.join("spoken-413.wav"))
        .unwrap_or_else(|e| panic!("fixtures/spoken-413.wav is unreadable ({e}); {hint}"));
    assert!(
        old_wav == fs::read(&wav).unwrap(),
        "fixtures/spoken-413.wav differs from a fresh render; {hint}"
    );

    let old_json = fs::read(checked_in.join("spoken-413.assessment.json")).unwrap_or_else(|e| {
        panic!("fixtures/spoken-413.assessment.json is unreadable ({e}); {hint}")
    });
    let old_value: serde_json::Value = serde_json::from_slice(&old_json).unwrap();
    let new_value: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert!(
        old_value == new_value,
        "fixtures/spoken-413.assessment.json differs from a fresh run; {hint}"
    );

    // R12: no null where a number belongs, so it reads back as the typed assessment.
    let typed: UtteranceAssessment = serde_json::from_slice(&old_json).unwrap();
    assert_eq!(typed.syllables.len(), 3);
    assert!(typed.margin_llr.is_finite());
    assert!(typed.overall.is_some_and(f32::is_finite));
    assert!(typed
        .syllables
        .iter()
        .all(|s| s.p_correct.is_finite() && s.distance.is_none_or(f32::is_finite)));
    // Cold start: every syllable is at best partial, never silently unmeasured.
    assert!(typed.syllables.iter().all(|s| matches!(
        &s.measured,
        Measured::Partial { issues } if issues.contains(&MeasureIssue::ColdStartRegister)
    )));
}
