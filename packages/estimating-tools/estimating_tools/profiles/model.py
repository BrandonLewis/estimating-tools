"""The resolved profile object consumers read from."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """A merged, resolved profile. `data` holds merged sections (e.g. 'argot',
    'letterhead', 'folder_conventions'); `sources` is the cascade-ordered list of
    source directory paths."""

    data: dict
    sources: tuple[str, ...] = ()

    def section(self, name: str) -> dict:
        value = self.data.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def is_empty(self) -> bool:
        return not self.data
