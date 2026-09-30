"""The `tkh` command line: a broken pyworld disables only the commands that need it."""

from __future__ import annotations

import subprocess
import sys

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


@pytest.mark.parametrize("command", ["eval", "ingest", "provenance"])
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
    for command in ("ingest", "provenance", "eval", "synth", "adversary"):
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
