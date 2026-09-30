"""The `tkh` command line: a broken pyworld disables only the commands that need it."""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

import tonekit_harness
from tonekit_harness import cli


@pytest.fixture
def broken_pyworld(monkeypatch):
    """`import pyworld` raises ImportError, and the modules that imported it are forgotten (from
    `sys.modules` and as attributes of the package, which `from . import x` consults first) so the
    parser has to import them again. All restored afterwards."""
    for name in ("world", "source", "synth", "adversary"):
        monkeypatch.delitem(sys.modules, f"tonekit_harness.{name}", raising=False)
        monkeypatch.delattr(tonekit_harness, name, raising=False)
    monkeypatch.setitem(sys.modules, "pyworld", None)


@pytest.mark.parametrize("command", ["eval", "ingest", "provenance", "bakeoff"])
def test_a_broken_pyworld_leaves_the_other_commands_working(broken_pyworld, command, capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main([command, "--help"])
    assert stop.value.code == 0
    assert f"usage: tkh {command}" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["synth", "adversary"])
def test_a_broken_pyworld_disables_only_synth_and_adversary_and_says_why(
    broken_pyworld, command, capsys
):
    # whatever arguments the command was given, it reports why it cannot run and exits non-zero
    assert cli.main([command, "--manifest", "m.jsonl", "--pack", "p.toml", "--out", "o"]) == 1
    err = capsys.readouterr().err
    assert err.startswith(f"error: tkh {command} is unavailable: cannot import {command} (")
    assert "pyworld" in err and "the other commands still work" in err


def test_the_top_level_help_still_lists_every_command_when_pyworld_is_broken(
    broken_pyworld, capsys
):
    with pytest.raises(SystemExit) as stop:
        cli.main(["--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    for command in ("ingest", "provenance", "eval", "bakeoff", "synth", "adversary"):
        assert command in out
    assert "unavailable" in out


def test_an_unknown_argument_to_a_working_command_is_still_an_error(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["provenance", "--register", "r.csv", "--no-such-flag"])
    assert stop.value.code == 2
    assert "unrecognized arguments: --no-such-flag" in capsys.readouterr().err


def test_with_pyworld_working_synth_and_adversary_are_registered(capsys):
    for command in ("synth", "adversary"):
        with pytest.raises(SystemExit) as stop:
            cli.main([command, "--help"])
        assert stop.value.code == 0
    assert "--noise-wav" in capsys.readouterr().out


def test_in_a_fresh_interpreter_a_broken_pyworld_does_not_stop_tkh_eval():
    """Importing `tonekit_harness.cli` itself must not need pyworld either."""
    program = (
        "import sys\n"
        "sys.modules['pyworld'] = None  # `import pyworld` raises ImportError\n"
        "from tonekit_harness import cli\n"
        "raise SystemExit(cli.main(sys.argv[1:]))\n"
    )

    def tkh(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", program, *argv], capture_output=True, text=True, check=False
        )

    ok = tkh("eval", "--help")
    assert ok.returncode == 0 and "usage: tkh eval" in ok.stdout
    bad = tkh("synth", "--manifest", "m.jsonl")
    assert bad.returncode == 1 and "tkh synth is unavailable" in bad.stderr


# ---- whatever a broken optional import raises ---------------------------------------------------


def failing_import(monkeypatch, error: BaseException) -> None:
    """Make the import of each optional command's module raise `error`."""

    def import_module(name, package=None):
        raise error

    monkeypatch.setattr(cli, "importlib", types.SimpleNamespace(import_module=import_module))


WINDOWS_ERROR = "[WinError 193] %1 is not a valid Win32 application"  # the real message, verbatim


@pytest.mark.parametrize("error_type", [ImportError, OSError])
def test_a_percent_sign_in_the_reason_does_not_break_the_help(
    monkeypatch, capsys, error_type
):
    failing_import(monkeypatch, error_type(WINDOWS_ERROR))
    for argv in (["--help"], ["eval", "--help"]):
        with pytest.raises(SystemExit) as stop:
            cli.main(argv)
        assert stop.value.code == 0
    # `tkh --help` lists the unavailable commands with the reason, percent sign intact
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "%1 is not a valid Win32 application" in out and "%%" not in out


def test_a_percent_sign_in_the_reason_reaches_the_error_message_unchanged(monkeypatch, capsys):
    failing_import(monkeypatch, OSError(WINDOWS_ERROR))
    assert cli.main(["synth", "--manifest", "m.jsonl"]) == 1
    err = capsys.readouterr().err
    assert "%1 is not a valid Win32 application" in err and "%%" not in err


@pytest.mark.parametrize(
    "error",
    [
        ValueError("numpy.dtype size changed, may indicate binary incompatibility"),
        RuntimeError("module compiled against API version 0x10 but this version of numpy is 0xf"),
        AttributeError("module 'numpy' has no attribute 'float_'"),
        ImportError("libgomp.so.1: cannot open shared object file"),
    ],
)
def test_any_failure_of_the_optional_import_disables_only_that_command(monkeypatch, capsys, error):
    failing_import(monkeypatch, error)
    with pytest.raises(SystemExit) as stop:
        cli.main(["eval", "--help"])
    assert stop.value.code == 0 and "usage: tkh eval" in capsys.readouterr().out
    assert cli.main(["adversary", "--manifest", "m.jsonl"]) == 1
    err = capsys.readouterr().err
    assert f"({type(error).__name__}: {error})" in err and "the other commands still work" in err


def test_ctrl_c_during_the_optional_import_is_not_swallowed(monkeypatch):
    failing_import(monkeypatch, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        cli.build_parser()
