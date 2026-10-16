"""Cost-code / activity-code id resolver (#203).

BM build scripts hard-code ``{activity_code_id: (code_string, label)}`` tables
(the database ids discovered by hand from ``list_activity_codes``). This is the
small cached resolver that removes those tables: bidirectional
``code_string <-> activity_code_id <-> label`` within ONE cost-code system,
built from a ``list_activity_codes`` result — or resolved lazily, one code at a
time, through a ``find_activity_code_by_code``-shaped callable.

Org-agnostic: it resolves within whatever ``system_id`` is passed and embeds no
org's codes. Pure stdlib — the live BM calls stay at the skill/agent layer; the
caller hands the rows (or a finder) in.

    r = CostCodeResolver.from_rows(list_activity_codes_result, system_id=1)
    r.id_of("03-600")            # -> 70
    r.code_of(70)                # -> "03-600"
    r.label_of("03-600")         # -> "Box Culvert / Channel"  (id or code)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# label field candidates in a BM activity-code record, in preference order
_LABEL_KEYS = ("description", "name", "label", "title")


@dataclass(frozen=True)
class ActivityCodeRef:
    """One resolved activity code: its database id, code string, and label."""

    id: int
    code: str
    label: str = ""


class CostCodeResolver:
    """Bidirectional code/id/label lookup within one cost-code system.

    Construct from ``list_activity_codes`` rows via :meth:`from_rows`, or pass a
    ``finder`` (a ``find_activity_code_by_code``-shaped ``code -> row|None``
    callable) for lazy, cached, one-at-a-time resolution — or both. Lookups are
    O(1); a miss raises ``KeyError`` naming the needle and some available codes
    (never a silent ``None``, which is how the hand-kept tables shipped wrong
    ids). Use :meth:`get` when a miss is acceptable.
    """

    def __init__(self, refs=(), *, system_id: int | None = None,
                 finder: Callable[[str], dict | None] | None = None,
                 label_keys=_LABEL_KEYS) -> None:
        self.system_id = system_id
        self._finder = finder
        self._label_keys = tuple(label_keys)
        self._by_code: dict[str, ActivityCodeRef] = {}
        self._by_id: dict[int, ActivityCodeRef] = {}
        for ref in refs:
            self._add(ref)

    # -- construction -------------------------------------------------------

    def _add(self, ref: ActivityCodeRef) -> ActivityCodeRef:
        prior = self._by_code.get(ref.code)
        if prior is not None and prior.id != ref.id:
            raise ValueError(
                f"duplicate code {ref.code!r} maps to both id {prior.id} and "
                f"{ref.id} — not a single cost-code system?")
        prior = self._by_id.get(ref.id)
        if prior is not None and prior.code != ref.code:
            raise ValueError(
                f"duplicate id {ref.id} maps to both code {prior.code!r} and "
                f"{ref.code!r} — not a single cost-code system?")
        self._by_code[ref.code] = ref
        self._by_id[ref.id] = ref
        return ref

    @classmethod
    def from_rows(cls, rows, *, system_id: int | None = None,
                  code_key: str = "code", id_key: str = "id",
                  label_keys=_LABEL_KEYS,
                  finder: Callable[[str], dict | None] | None = None
                  ) -> "CostCodeResolver":
        """Build from ``list_activity_codes`` result rows.

        Rows lacking both keys — e.g. a BM ``{"error": ...}`` sentinel or a
        non-dict — are skipped; a row that has an id but no code (or vice
        versa) is a real malformed record and raises.
        """
        refs = [cls._ref_from_row(row, code_key, id_key, label_keys)
                for row in rows
                if isinstance(row, dict) and (code_key in row or id_key in row)]
        return cls(refs, system_id=system_id, finder=finder,
                   label_keys=label_keys)

    @staticmethod
    def _ref_from_row(row: dict, code_key: str, id_key: str,
                      label_keys) -> ActivityCodeRef:
        if code_key not in row:
            raise ValueError(f"activity-code row missing {code_key!r}: {row!r}")
        if id_key not in row:
            raise ValueError(f"activity-code row missing {id_key!r}: {row!r}")
        label = next((str(row[k]) for k in label_keys if row.get(k)), "")
        return ActivityCodeRef(id=int(row[id_key]), code=str(row[code_key]),
                               label=label)

    # -- lookup -------------------------------------------------------------

    def _lookup(self, key) -> ActivityCodeRef | None:
        """Resolve a code (str) or id (int) to a ref, consulting the finder."""
        if isinstance(key, bool):        # bool is an int subclass — reject
            return None
        if isinstance(key, int):
            return self._by_id.get(key)
        ref = self._by_code.get(key)
        if ref is None and self._finder is not None:
            row = self._finder(key)
            # Same contract as from_rows: a row carrying at least one required
            # key is validated (a half-populated row raises rather than caching
            # an invented code); anything else — None, a non-dict, or a bare
            # {"error": ...} sentinel — is a miss. Configured label_keys apply.
            if isinstance(row, dict) and ("code" in row or "id" in row):
                ref = self._add(self._ref_from_row(
                    row, "code", "id", self._label_keys))
        return ref

    def _require(self, key) -> ActivityCodeRef:
        ref = self._lookup(key)
        if ref is None:
            kind = "id" if isinstance(key, int) else "code"
            avail = ", ".join(self.codes()[:12]) or "(none loaded)"
            raise KeyError(
                f"no activity {kind} {key!r} in system {self.system_id} "
                f"— available codes: {avail}")
        return ref

    def id_of(self, code: str) -> int:
        return self._require(code).id

    def code_of(self, code_id: int) -> str:
        return self._require(code_id).code

    def label_of(self, code_or_id) -> str:
        return self._require(code_or_id).label

    def ref(self, code_or_id) -> ActivityCodeRef:
        return self._require(code_or_id)

    def get(self, code_or_id, default=None):
        """Non-raising lookup → the :class:`ActivityCodeRef` or ``default``."""
        return self._lookup(code_or_id) or default

    # -- introspection ------------------------------------------------------

    def __contains__(self, code_or_id) -> bool:
        return self._lookup(code_or_id) is not None

    def __len__(self) -> int:
        return len(self._by_id)

    def codes(self) -> list[str]:
        return sorted(self._by_code)

    def ids(self) -> list[int]:
        return sorted(self._by_id)
