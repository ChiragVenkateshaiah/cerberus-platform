"""ADR 0024 rule 5, second line of defence behind ruff's S rules: no eval/exec,
no way to run a program, in the package."""

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "cerberus_console"
FILES = sorted(PKG.glob("*.py"))
BANNED_CALLS = {"eval", "exec", "compile", "__import__"}
BANNED_MODULES = {"subprocess", "pickle", "marshal", "shelve", "ctypes"}
BANNED_ATTRS = {("os", n) for n in ("system", "popen", "execv", "execvp", "spawnv")}


def test_package_files_found():
    assert len(FILES) >= 10


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_banned_calls_or_imports(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in BANNED_CALLS, (path.name, node.lineno)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                assert (node.func.value.id, node.func.attr) not in BANNED_ATTRS
            assert node.func.attr != "import_module", (path.name, node.lineno)
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in BANNED_MODULES, (path.name, node.lineno)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in BANNED_MODULES, (path.name, node.lineno)
            if node.module == "os":
                assert not {a.name for a in node.names} & {n for _, n in BANNED_ATTRS}


def test_boto3_is_imported_only_in_aws_py_and_only_inside_functions():
    for path in FILES:
        tree = ast.parse(path.read_text())
        top_level = {id(n) for n in tree.body}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n.split(".")[0] in ("boto3", "botocore") for n in names):
                assert path.name == "aws.py", path.name
                assert id(node) not in top_level, "boto3 must be imported lazily"


def test_urllib_request_is_imported_only_in_aws_py():
    """The AMP reader (10.5a) is the one place that opens a network connection."""
    for path in FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            hit = False
            if isinstance(node, ast.Import):
                hit = any(a.name.split(".")[:2] == ["urllib", "request"] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                hit = mod.split(".")[:2] == ["urllib", "request"] or (
                    mod == "urllib" and any(a.name == "request" for a in node.names)
                )
            if hit:
                assert path.name == "aws.py", (path.name, node.lineno)


def test_no_other_network_module_is_imported_anywhere():
    banned = {"socket", "http", "requests", "httpx", "ftplib", "smtplib", "telnetlib"}
    for path in FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for n in names:
                assert n.split(".")[0] not in banned, (path.name, node.lineno)
