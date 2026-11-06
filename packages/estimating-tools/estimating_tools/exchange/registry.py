"""Pack discovery. Packs register under the ``estimating_tools.packs`` entry
point group, each entry a callable returning a ``Pack``. The CLI and the
skills call ``pack_for`` and never name a pack. Entry points are loaded only
inside functions, never at import time: ``exchange/__init__`` imports this
module, and a pack that imports ``exchange.types`` must not recurse into
loading itself."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import get_args

from estimating_tools.exchange.types import BookFacts, Verdict

PACKS_GROUP = "estimating_tools.packs"
VERDICTS = frozenset(get_args(Verdict))


@dataclass(frozen=True)
class Discovery:
    """What discovery found: the packs that loaded, by name, and one line per
    entry point that did not (a failed import, a factory that raised, a name
    collision). The CLI prints the problems; ``pack_for`` appends them to its
    refusals so a user whose book belongs to a broken pack learns why."""
    packs: list
    problems: list = field(default_factory=list)


def _entry_points() -> list:
    """The raw entry points of the group (the seam tests replace)."""
    return list(entry_points(group=PACKS_GROUP))


def discover() -> Discovery:
    packs, problems, seen = [], [], {}
    for ep in _entry_points():
        try:
            pack = ep.load()()
        except Exception as exc:  # noqa: BLE001 -- a broken pack is reported, not fatal
            problems.append(f"pack {ep.name} ({ep.value}) failed to load: {exc}")
            continue
        name = getattr(pack, "name", None)
        if not isinstance(name, str) or not name:
            problems.append(f"pack {ep.name} ({ep.value}) has no name; ignored")
            continue
        if name in seen:
            problems.append(f"two packs are both named {name!r} ({seen[name]} and "
                            f"{ep.value}); the second is ignored")
            continue
        seen[name] = ep.value
        packs.append(pack)
    packs.sort(key=lambda p: p.name)
    return Discovery(packs, problems)


def packs() -> list:
    """Every installed pack that loads, by name."""
    return discover().packs


def pack_for(facts: BookFacts):
    """The one pack whose ``detect`` says ``ok``. Raises LookupError with a
    message the CLI prints verbatim."""
    found = discover()
    problems = list(found.problems)
    verdicts = []
    for p in found.packs:
        try:
            v = p.detect(facts)
        except Exception as exc:  # noqa: BLE001 -- one bad detect must not stop the rest
            problems.append(f"{p.name}: detect failed: {exc}")
            v = "none"
        if not isinstance(v, str) or v not in VERDICTS:
            problems.append(f"{p.name} returned an unknown verdict {v!r}")
            v = "none"
        verdicts.append((p, v))
    suffix = (" -- problems: " + "; ".join(problems)) if problems else ""
    ok = [p for p, v in verdicts if v == "ok"]
    if len(ok) == 1:
        return ok[0]
    if len(ok) > 1:
        raise LookupError("two packs claim this book: " + ", ".join(p.name for p in ok))
    for p, v in verdicts:
        if v == "newer":
            raise LookupError(f"this book was made by a newer version of the {p.name} pack -- "
                              f"update the plugin{suffix}")
    for p, v in verdicts:
        if v == "bad":
            raise LookupError(f"this is a {p.name} book but its stamp is damaged -- "
                              f"rebuild it{suffix}")
    raise LookupError("no installed pack recognizes this book "
                      f"(installed: {', '.join(p.name for p, _ in verdicts) or 'none'}){suffix}")
