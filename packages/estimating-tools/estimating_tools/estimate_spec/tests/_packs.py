"""Throwaway copies of the legacy_demo fixture pack with patched documents."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable

import yaml

from estimating_tools.estimate_spec import format_pack as fp

LEGACY_DIR = Path(__file__).resolve().parent / "fixtures" / "packs" / "legacy_demo"
LEGACY_EXAMPLE = LEGACY_DIR / "examples" / "demo-pipeline.estimate.yaml"
_DOCS = {"format": "format.yaml", "units": "units.yaml", "tokens": "tokens.yaml",
         "recipes": "recipes.yaml", "vocabulary": "vocabulary.yaml", "seed": "seed.yaml"}


class _NoAliasDumper(yaml.SafeDumper):
    """A SafeDumper that never emits YAML aliases.

    legacy_demo's recipes.yaml shares structure with `&header`/`*header`
    (etc.) anchors. `yaml.safe_load` resolves those into the SAME Python
    object at every alias site, so mutating one in place would silently
    mutate every other alias of it too. Round-tripping through this dumper
    (ignore_aliases always True) before an edit is applied, and again when
    writing the patched document back out, breaks that sharing: every site
    becomes an independent object and no `&id`-anchors are written.
    """

    def ignore_aliases(self, data):
        return True


def _dump_no_aliases(data) -> str:
    return yaml.dump(data, Dumper=_NoAliasDumper, sort_keys=False)


def _load_independent(path: Path) -> dict:
    """Load `path`'s YAML with every anchor/alias expanded into its own copy."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return yaml.safe_load(_dump_no_aliases(data))


def legacy_example() -> dict:
    return yaml.safe_load(LEGACY_EXAMPLE.read_text(encoding="utf-8"))


def patched_pack(tmp_path: Path, **edits: Callable[[dict], None]) -> fp.FormatPack:
    """Copy legacy_demo under a fresh directory inside tmp_path, apply edits, load it.

    Each keyword names a document (format, units, tokens, recipes,
    vocabulary, seed) and maps to a callable that mutates that document's
    parsed YAML in place.

    A caller may invoke this more than once against the same tmp_path (or a
    subdirectory of it): each call gets its own unique copy of legacy_demo
    (via `tempfile.mkdtemp`), so the copies never collide.
    """
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(dir=tmp_path)) / "pack"
    shutil.copytree(LEGACY_DIR, root)
    for doc, edit in edits.items():
        if doc not in _DOCS:
            raise ValueError(f"unknown pack document {doc!r}; expected one of {sorted(_DOCS)}")
        path = root / _DOCS[doc]
        data = _load_independent(path)
        edit(data)
        path.write_text(_dump_no_aliases(data), encoding="utf-8")
    return fp.load_pack(root)
