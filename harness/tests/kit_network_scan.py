"""The scan behind "DJ never sends your recordings to any other service" (R71): it reads the harness's
Python source for imports of network clients, and for imports it cannot read (dynamic ones). A tripwire,
not a proof. Whoever needs a network client for a good reason changes this list on purpose, and that edit
is the moment to ask whether volunteer audio could reach it."""

from __future__ import annotations

import ast
from pathlib import Path

NETWORK_MODULES = (
    "requests", "httpx", "aiohttp", "urllib3", "urllib.request", "socket", "_socket", "ssl", "asyncio",
    "socketserver", "http.client", "http.server", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
    "xmlrpc", "websockets", "paramiko", "grpc", "boto3", "botocore", "google.cloud", "azure", "tencentcloud",
    "huggingface_hub", "subprocess", "webbrowser", "multiprocessing.connection", "flask", "fsspec", "pooch",
    "sentry_sdk",
)  # fmt: skip

LOADERS = {"import_module", "__import__"}  # importlib's, and the builtin


def is_network_module(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in NETWORK_MODULES)


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _loader_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """The names this file gives importlib (`import importlib as il`; `import importlib.util` binds
    `importlib` too) and its loaders (`from importlib import import_module as load`)."""
    modules, functions = set(), {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    modules.add(alias.asname or alias.name)
                elif alias.name.startswith("importlib.") and alias.asname is None:
                    modules.add("importlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib" and node.level == 0:
            functions.update(a.asname or a.name for a in node.names if a.name in LOADERS)
    return modules, functions


def _is_own_package_load(call: ast.Call) -> bool:
    """`import_module(f".{name}", __package__)`: a module of the harness itself, named relative to it."""
    if len(call.args) != 2 or call.keywords:
        return False
    name, package = call.args
    if not (isinstance(package, ast.Name) and package.id == "__package__"):
        return False
    first = name.values[0] if isinstance(name, ast.JoinedStr) and name.values else name
    return isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.startswith(".")


def _dynamic_imports(tree: ast.AST) -> list[str]:
    modules, functions = _loader_aliases(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        loader = (isinstance(func, ast.Name) and func.id in functions) or (
            isinstance(func, ast.Attribute)
            and func.attr in LOADERS
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        )
        if loader and not _is_own_package_load(node):
            found.append(f"dynamic import on line {node.lineno}")
    return found


def network_imports(root: Path) -> dict[str, list[str]]:
    """Every .py file under `root` that imports a network client or loads a module by a name it can't
    show: path (relative to `root`) -> what was found."""
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = sorted(n for n in _imported_names(tree) if is_network_module(n)) + _dynamic_imports(tree)
        if bad:
            found[path.relative_to(root).as_posix()] = bad
    return found
