"""deck_build.rows: the CSV sources, with the file and line in every complaint."""

import pytest

from tonekit_harness.deck_build.errors import BuildError
from tonekit_harness.deck_build.rows import read_rows


def write(tmp_path, text, name="s.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_rows_are_stripped_and_blank_lines_skipped(tmp_path):
    path = write(tmp_path, "a,b\n x , y \n\n,\n1,2\n")
    rows = read_rows(path, required=["a", "b"])
    assert [dict(r.values) for r in rows] == [{"a": "x", "b": "y"}, {"a": "1", "b": "2"}]
    assert [r.where for r in rows] == ["s.csv:2", "s.csv:5"]


def test_a_spreadsheet_byte_order_mark_is_ignored(tmp_path):
    path = tmp_path.joinpath("bom.csv")
    path.write_bytes("﻿a,b\n1,2\n".encode())
    assert read_rows(path, required=["a", "b"])[0].get("a") == "1"


def test_a_missing_column_names_the_header(tmp_path):
    with pytest.raises(BuildError, match=r"s\.csv: missing column\(s\) c \(header has: a, b\)"):
        read_rows(write(tmp_path, "a,b\n1,2\n"), required=["a", "c"])


def test_a_misspelt_column_is_an_error_in_a_strict_source(tmp_path):
    path = write(tmp_path, "a,b,flaq\n1,2,3\n")
    with pytest.raises(BuildError, match="unknown column.*flaq"):
        read_rows(path, required=["a", "b"], optional=["flag"])
    assert len(read_rows(path, required=["a", "b"], optional=["flag"], strict=False)) == 1


def test_a_value_the_row_needs_is_named_when_empty(tmp_path):
    row = read_rows(write(tmp_path, "a,b\n1,\n"), required=["a", "b"])[0]
    assert row.need("a") == "1"
    with pytest.raises(BuildError, match=r"s\.csv:2: b is empty"):
        row.need("b")


def test_extra_values_and_missing_files_are_errors(tmp_path):
    with pytest.raises(BuildError, match=r"s\.csv:2: more values"):
        read_rows(write(tmp_path, "a,b\n1,2,3\n"), required=["a", "b"])
    with pytest.raises(BuildError, match="cannot read"):
        read_rows(tmp_path / "nope.csv", required=["a"])
