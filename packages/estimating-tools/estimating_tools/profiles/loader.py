"""Discover, parse, per-field-validate, and resolve profiles into a Profile."""
from __future__ import annotations

import functools
import json
import os
import warnings
from collections.abc import Mapping
from pathlib import Path

import jsonschema
import yaml

from estimating_tools.profiles.merge import merge
from estimating_tools.profiles.model import Profile

SCHEMA_PATH = Path(__file__).parent / "schema" / "profile.schema.json"
# (section, field) references that name a file inside the profile directory.
_ASSET_FIELDS = [("letterhead", "template"), ("letterhead", "logo"),
                 ("folder_conventions", "tree"), ("estimating", "format")]


def discover(env: Mapping[str, str] | None = None) -> list[Path]:
    """Ordered list of existing profile directories from ESTIMATING_PROFILES."""
    env = os.environ if env is None else env
    dirs: list[Path] = []
    for part in env.get("ESTIMATING_PROFILES", "").split(os.pathsep):
        if not part:
            continue
        path = Path(part)
        if path.is_dir():
            dirs.append(path)
        else:
            warnings.warn(f"ESTIMATING_PROFILES entry is not a directory, skipped: {part}")
    return dirs


@functools.lru_cache(maxsize=None)
def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _validate_fields(sections: dict, schema: dict) -> dict:
    """Validate each top-level field against its subschema; drop+warn on failure."""
    props = schema.get("properties", {})
    out: dict = {}
    for key, value in sections.items():
        sub = props.get(key)
        if sub is None:
            warnings.warn(f"profile: unknown field '{key}' dropped")
            continue
        try:
            jsonschema.validate(value, sub)
        except jsonschema.ValidationError as exc:
            warnings.warn(f"profile: field '{key}' invalid, dropped: {exc.message}")
            continue
        out[key] = value
    return out


def _resolve_assets(sections: dict, base: Path) -> dict:
    for sect, field in _ASSET_FIELDS:
        node = sections.get(sect)
        if isinstance(node, dict) and isinstance(node.get(field), str):
            ref = Path(node[field])
            if not ref.is_absolute():
                node[field] = str((base / ref).resolve())
    return sections


def load_one(directory: Path) -> dict:
    """Parse + validate + asset-resolve a single profile directory's profile.yaml.

    An empty or comment-only profile.yaml yields an empty section set (no error).
    """
    raw = yaml.safe_load((Path(directory) / "profile.yaml").read_text())
    if not isinstance(raw, dict):
        if raw is not None:
            warnings.warn(f"profile: {directory}/profile.yaml is not a mapping; ignored")
        return {}
    validated = _validate_fields(raw, _schema())
    return _resolve_assets(validated, Path(directory))


def load(dirs: list[Path] | None = None) -> Profile:
    """Discover (or use given dirs), load each, cascade-merge, return a Profile.

    With no dirs (and ESTIMATING_PROFILES unset), returns an empty Profile so
    every consumer falls back to its agnostic default.
    """
    if dirs is None:
        dirs = discover()
    layers = [load_one(d) for d in dirs]
    return Profile(data=merge(layers), sources=tuple(str(d) for d in dirs))
