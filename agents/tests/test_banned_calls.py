"""ADR 0024 rule 5 for agents/, behind ruff's S rules: no eval/exec, no way to
run a program, no serialised-object loader, no boto3 in the package (14.2a)."""

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "cerberus_agents"
FILES = sorted(PKG.glob("*.py"))
BANNED_CALLS = {"eval", "exec", "compile", "__import__"}
BANNED_MODULES = {"subprocess", "pickle", "marshal", "shelve", "ctypes", "boto3", "botocore"}
BANNED_ATTRS = {("os", n) for n in ("system", "popen", "execv", "execvp", "spawnv")}


def test_package_files_found():
    assert {p.name for p in FILES} >= {"__init__.py", "review.py", "evidence.py", "baselines.py"}


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
