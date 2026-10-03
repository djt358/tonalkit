"""R71, the mechanism behind "DJ never ... sends [your recordings] to any other service": the harness
imports no network client and loads no module by a name the scan can't read."""

import pytest
from kit_network_scan import network_imports
from kit_support import REPO

HARNESS_SRC = REPO / "harness" / "src"


def scan(tmp_path, source: str) -> dict[str, list[str]]:
    (tmp_path / "module.py").write_text(source, encoding="utf-8")
    return network_imports(tmp_path)


def test_the_harness_imports_no_network_client_and_loads_nothing_by_a_hidden_name():
    assert network_imports(HARNESS_SRC) == {}


@pytest.mark.parametrize(
    "line",
    [
        "import requests",
        "from urllib import request",
        "from urllib.request import urlopen",
        "import socket",
        "import ssl",
        "import asyncio",
        "from socketserver import TCPServer",
        "import _socket",
        "import subprocess",
        "import webbrowser",
        "from multiprocessing.connection import Client",
        "import flask",
        "import fsspec",
        "import pooch",
        "import sentry_sdk",
        "import http.client as h",
    ],
)
def test_the_scan_sees_a_network_import(tmp_path, line):
    assert list(scan(tmp_path, line + "\n")) == ["module.py"]


@pytest.mark.parametrize(
    "source",
    [
        "__import__('socket')",
        "import importlib\nimportlib.import_module('socket')",
        "import importlib.util\nimportlib.import_module('socket')",
        "import importlib.metadata\nimportlib.import_module(name)",
        "import importlib\nimportlib.import_module(name)",
        "import importlib as il\nil.import_module('requests')",
        "from importlib import import_module\nimport_module(name)",
        "from importlib import import_module as load\nload(name)",
        "import importlib\nimportlib.import_module(f'.{name}')",
        "import importlib\nimportlib.import_module(f'{name}', __package__)",
        "import importlib\nimportlib.import_module(f'.{name}', 'socket')",
        "import importlib\nimportlib.__import__('socket')",
    ],
)
def test_the_scan_sees_an_import_by_a_name_it_cannot_read(tmp_path, source):
    (found,) = scan(tmp_path, source + "\n").values()
    assert found[0].startswith("dynamic import on line")


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nimportlib.import_module(f'.{name}', __package__)",
        "from importlib import import_module\nimport_module('.cli', __package__)",
    ],
)
def test_the_scan_lets_the_harness_load_its_own_modules_relative_to_its_package(tmp_path, source):
    assert scan(tmp_path, source + "\n") == {}


def test_the_scan_leaves_ordinary_imports_alone(tmp_path):
    source = "import urllib.parse\nfrom pathlib import Path\nimport json\nfrom importlib import metadata\n"
    assert scan(tmp_path, source) == {}
