from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from tonekit_harness import cli, ingest

SR_OUT = 16_000


def sine(freq: float, sr: int, n: int, amp: float = 0.5) -> np.ndarray:
    return amp * np.sin(2 * np.pi * freq * np.arange(n) / sr)


def write_pcm16(path: Path, sr: int, data: np.ndarray) -> None:
    wavfile.write(path, sr, np.round(data * 32767).astype(np.int16))


def read_out(path: Path):
    sr, data = wavfile.read(path)
    return sr, data


def peak_freq(x: np.ndarray, sr: int) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spec) * sr / len(x))


def test_44k_stereo_becomes_16k_mono_and_duration_is_preserved(tmp_path):
    sr, n = 44_100, 22_050  # 0.5 s
    left, right = sine(440, sr, n), sine(440, sr, n)
    src = tmp_path / "in.wav"
    write_pcm16(src, sr, np.stack([left, right], axis=1))

    out = tmp_path / "out.wav"
    ingest.to_16k_mono(src, out)

    out_sr, data = read_out(out)
    assert out_sr == SR_OUT
    assert data.ndim == 1
    assert data.dtype == np.float32
    assert abs(len(data) / out_sr - n / sr) <= 0.001
    assert abs(peak_freq(data, out_sr) - 440) < 2


@pytest.mark.parametrize("sr", [8_000, 22_050, 32_000, 44_100, 48_000, 96_000])
@pytest.mark.parametrize("n_frames", [1_000, 12_345])
def test_duration_within_1ms_for_any_rate_and_odd_length(tmp_path, sr, n_frames):
    src = tmp_path / "in.wav"
    write_pcm16(src, sr, sine(300, sr, n_frames))
    out = tmp_path / "out.wav"
    ingest.to_16k_mono(src, out)
    out_sr, data = read_out(out)
    assert out_sr == SR_OUT
    assert abs(len(data) / out_sr - n_frames / sr) <= 0.001


def test_stereo_is_averaged_not_summed_or_dropped(tmp_path):
    sr, n = 16_000, 1_600
    left = np.full(n, 0.5)
    right = np.full(n, -0.25)
    src = tmp_path / "in.wav"
    write_pcm16(src, sr, np.stack([left, right], axis=1))
    out = tmp_path / "out.wav"
    ingest.to_16k_mono(src, out)
    _, data = read_out(out)
    assert data.shape == (n,)
    np.testing.assert_allclose(data, 0.125, atol=1e-3)


def test_int16_is_scaled_to_unit_range_and_16k_mono_is_not_resampled(tmp_path):
    x = np.array([0, 16384, -16384, 32767, -32768], dtype=np.int16)
    src = tmp_path / "in.wav"
    wavfile.write(src, SR_OUT, x)
    out = tmp_path / "out.wav"
    ingest.to_16k_mono(src, out)
    _, data = read_out(out)
    np.testing.assert_allclose(data, x / 32768.0, atol=1e-7)


def test_float_input_passes_through(tmp_path):
    x = (0.3 * np.sin(np.arange(800) / 7.0)).astype(np.float32)
    src = tmp_path / "in.wav"
    wavfile.write(src, SR_OUT, x)
    out = tmp_path / "out.wav"
    ingest.to_16k_mono(src, out)
    sr, data = read_out(out)
    assert sr == SR_OUT and data.dtype == np.float32
    np.testing.assert_array_equal(data, x)


def test_uint8_and_int32_are_scaled(tmp_path):
    u8 = tmp_path / "u8.wav"
    wavfile.write(u8, SR_OUT, np.array([128, 255, 0], dtype=np.uint8))
    i32 = tmp_path / "i32.wav"
    wavfile.write(i32, SR_OUT, np.array([0, 2**30, -(2**31)], dtype=np.int32))
    for src, expect in ((u8, [0.0, 127 / 128, -1.0]), (i32, [0.0, 0.5, -1.0])):
        out = src.with_name("out_" + src.name)
        ingest.to_16k_mono(src, out)
        _, data = read_out(out)
        np.testing.assert_allclose(data, expect, atol=1e-6)


def test_output_parent_directory_is_created(tmp_path):
    src = tmp_path / "in.wav"
    write_pcm16(src, SR_OUT, sine(200, SR_OUT, 1_600))
    out = tmp_path / "a" / "b" / "out.wav"
    ingest.to_16k_mono(src, out)
    assert out.exists()


# --- tkh ingest ---------------------------------------------------------------------------


def make_raw(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_pcm16(raw / "a.wav", 44_100, np.stack([sine(440, 44_100, 4_410)] * 2, axis=1))
    write_pcm16(raw / "b.WAV", 48_000, sine(220, 48_000, 4_800))
    (raw / "notes.txt").write_text("not audio")
    return raw


def test_cli_ingest_defaults_to_sibling_ingested_dir(tmp_path, capsys):
    raw = make_raw(tmp_path)
    assert cli.main(["ingest", str(raw)]) == 0
    out = tmp_path / "ingested"
    assert sorted(p.name for p in out.iterdir()) == ["a.wav", "b.wav"]
    for p in out.iterdir():
        sr, data = read_out(p)
        assert sr == SR_OUT and data.ndim == 1
    assert "2" in capsys.readouterr().out


def test_cli_ingest_out_option(tmp_path):
    raw = make_raw(tmp_path)
    dest = tmp_path / "corpus" / "dj"
    assert cli.main(["ingest", str(raw), "--out", str(dest)]) == 0
    assert sorted(p.name for p in dest.iterdir()) == ["a.wav", "b.wav"]
    assert not (tmp_path / "ingested").exists()


def test_cli_ingest_missing_dir_fails(tmp_path, capsys):
    assert cli.main(["ingest", str(tmp_path / "nope")]) == 1
    assert "nope" in capsys.readouterr().err


def test_cli_ingest_dir_without_wavs_fails(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["ingest", str(empty)]) == 1
    assert "no .wav" in capsys.readouterr().err


def test_cli_ingest_refuses_to_overwrite_source_dir(tmp_path, capsys):
    raw = make_raw(tmp_path)
    before = (raw / "a.wav").read_bytes()
    assert cli.main(["ingest", str(raw), "--out", str(raw)]) == 1
    assert (raw / "a.wav").read_bytes() == before
    assert "same" in capsys.readouterr().err
