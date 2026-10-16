"""Cross-reference validation for the estimate spec (Phase 4.5).

JSON Schema draft 2020-12 cannot cross-reference within a document, so
constraints of the form "item.crew_id must match some crews[].id" and
"crews[].members[].trade must match some rate_table[].trade" live here.

Called at the top of build.generate so a build never proceeds with an
inconsistent config. Pure; no I/O.
"""
from __future__ import annotations


def validate_cross_references(config: dict) -> None:
    """Raise ValueError with a locator on the first cross-reference violation.

    Checks:
      1. Every `crews[].id` is unique across the array.
      2. Every `crews[].members[].trade` matches some `rate_table[].trade`.
      3. Every `items[].crew_id` (when set) matches some `crews[].id`.

    Silent on a healthy config."""
    crews = config.get("crews") or []
    _check_crew_id_uniqueness(crews)
    _check_crew_member_trades(crews, config.get("rate_table") or [])
    _check_item_crew_id_references(config.get("items") or [], crews)


def _check_crew_id_uniqueness(crews: list[dict]) -> None:
    seen: dict[str, int] = {}
    for i, crew in enumerate(crews):
        cid = crew.get("id")
        if cid is None:
            raise ValueError(
                f"crews[{i}]: missing required 'id'"
            )
        if cid in seen:
            raise ValueError(
                f"crews: duplicate id {cid!r} at index {seen[cid]} and index {i}"
            )
        seen[cid] = i


def _check_crew_member_trades(crews: list[dict], rate_table: list[dict]) -> None:
    known_trades = {row.get("trade") for row in rate_table if row.get("trade") is not None}
    for crew in crews:
        cid = crew.get("id") or "<unnamed>"
        members = crew.get("members")
        if not members:
            raise ValueError(
                f"crews[{cid!r}]: missing or empty 'members' (crews must declare at least one member)"
            )
        for j, member in enumerate(members):
            trade = member.get("trade")
            if trade is None:
                raise ValueError(
                    f"crews[{cid!r}].members[{j}]: missing required 'trade'"
                )
            if trade not in known_trades:
                raise ValueError(
                    f"crews[{cid!r}].members[{j}]: trade {trade!r} has no matching "
                    f"entry in rate_table"
                )


def _check_item_crew_id_references(items: list[dict], crews: list[dict]) -> None:
    known_ids = {crew.get("id") for crew in crews if crew.get("id") is not None}
    for item in items:
        crew_id = item.get("crew_id")
        if crew_id is None:
            continue
        if crew_id not in known_ids:
            item_no = item.get("item_no", "<unnamed>")
            raise ValueError(
                f"item {item_no!r}: crew_id {crew_id!r} does not match any crews[].id"
            )
