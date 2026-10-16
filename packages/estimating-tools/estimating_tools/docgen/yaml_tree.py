"""YAML-driven directory tree walker with `{var}` interpolation."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping

import yaml


def _interp(value: str, ctx: Mapping[str, Any]) -> str:
    """Format `value` with ctx; missing keys raise KeyError."""
    return value.format(**ctx)


def _build_folders(base: Path, entries: list, ctx: Mapping[str, Any]) -> None:
    for entry in entries:
        if isinstance(entry, str):
            (base / _interp(entry, ctx)).mkdir(parents=True, exist_ok=True)
        elif isinstance(entry, dict):
            # Single-key dict: {parent_name: [children, ...]}
            for parent_name, children in entry.items():
                parent_dir = base / _interp(parent_name, ctx)
                parent_dir.mkdir(parents=True, exist_ok=True)
                _build_folders(parent_dir, children or [], ctx)
        else:
            raise TypeError(f"Unsupported folder entry: {entry!r}")


def build_tree(base: Path, yaml_text: str, ctx: Mapping[str, Any]) -> None:
    """Materialize folders under `base` per the YAML spec.

    YAML schema:
        folders:
          - "literal-name"
          - "{var}-interpolated"
          - parent-name:
              - child-a
              - child-b
    """
    spec = yaml.safe_load(yaml_text) or {}
    folders = spec.get("folders", [])
    _build_folders(base, folders, ctx)


def build_tree_from_spec(base: Path, folders: list, ctx: Mapping[str, Any]) -> None:
    """Materialize folders from an already-parsed Python list.

    Use when the caller has already parsed YAML and wants to pass a sub-list
    (e.g., `spec["folders"]`) without round-tripping through `yaml.safe_dump`.
    """
    _build_folders(base, folders or [], ctx)
