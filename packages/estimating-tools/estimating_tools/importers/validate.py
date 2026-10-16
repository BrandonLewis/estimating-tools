"""Validate a canonical-estimate dict against the JSON schema."""
from __future__ import annotations

import functools
import json
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).parent / "schema" / "canonical-estimate.schema.json"


@functools.lru_cache(maxsize=None)
def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate_canonical(data: dict) -> None:
    """Raise jsonschema.ValidationError if `data` is not a valid canonical estimate."""
    jsonschema.validate(data, _schema())
