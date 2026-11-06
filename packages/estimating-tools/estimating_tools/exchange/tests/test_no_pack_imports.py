"""Engine rule (spec, Layer 1): ``exchange/`` never imports from a pack package.
A second pack's errors must reach the CLI through ``BuildRefused`` and
``NotYet``, never through the pack's own types. The check walks the AST, so
no formatting (a parenthesised import, a continuation line) evades it."""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).parents[1]
PACK_PREFIXES = ("estimating_tools.heavybook", "estimating_tools.estimate_spec")
PACK_NAMES = ("heavybook", "estimate_spec")


def _is_pack(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in PACK_PREFIXES)


def _offending_imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_pack(alias.name) for alias in node.names):
                yield node
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_pack(module):
                yield node
            elif module == "estimating_tools" and any(alias.name in PACK_NAMES
                                                      for alias in node.names):
                yield node


def test_exchange_imports_no_pack_package():
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        parts = path.relative_to(PACKAGE).parts
        if "tests" in parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _offending_imports(tree):
            offenders.append(f"{path.relative_to(PACKAGE).as_posix()}: {node.lineno}")
    assert offenders == []
