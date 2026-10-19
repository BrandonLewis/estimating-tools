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
      4. A rate_table row with a wage breakdown reproduces its rate within $0.01.
      5. Work packages: unique names, items that exist, task lines that name a
         package listing their item, picks/carry keyed by the package's items.

    Silent on a healthy config."""
    crews = config.get("crews") or []
    _check_crew_id_uniqueness(crews)
    _check_crew_member_trades(crews, config.get("rate_table") or [])
    _check_item_crew_id_references(config.get("items") or [], crews)
    _check_rate_breakdowns(config.get("rate_table") or [])
    if config.get("work_packages"):
        _check_work_packages(config)


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


def _check_rate_breakdowns(rate_table: list[dict]) -> None:
    """base * (1 + burden_pct) + fringe is BidManager's burdened-rate formula;
    a row carrying the parts must agree with the rate it states."""
    for i, row in enumerate(rate_table):
        if "base" not in row:
            continue
        built = row["base"] * (1 + row.get("burden_pct", 0)) + row.get("fringe", 0)
        if abs(built - row["rate"]) > 0.01 + 1e-9:
            raise ValueError(
                f"rate_table[{i}] ({row.get('trade')!r}): base * (1 + burden_pct) + "
                f"fringe = {built:.2f}, but rate is {row['rate']:.2f}")


def _package_line_names(name: str, item: dict) -> list[str]:
    return [line["name"] for block in item.get("labor") or []
            for line in block.get("lines") or [] if line.get("package") == name]


def _check_carry_key(name: str, key: str, listed: set[str], items: list[dict]) -> None:
    """A `carry` key is `<item_no>` (an item with one package line) or
    `<item_no>/<line name>`; its value is that package line's CARRY $/unit."""
    n, sep, line = key.partition("/")
    if n not in listed:
        raise ValueError(f"work_packages[{name}].carry: item '{n}' is not in the package")
    (item,) = [i for i in items if str(i["item_no"]) == n]
    lines = _package_line_names(name, item)
    if sep:
        if line not in lines:
            raise ValueError(f"work_packages[{name}].carry: line '{key}' is not a package line")
    elif len(lines) > 1:
        raise ValueError(f"work_packages[{name}].carry: item '{n}' has several package lines; "
                         f"key it as '{n}/<line name>' (lines: {', '.join(lines)})")


def _check_work_packages(config: dict) -> None:
    """Package names are unique; package items exist; each `line.package` names a
    package that lists the line's item; `picks` keys are the package's items; `carry`
    keys are `<item_no>` (one package line) or `<item_no>/<line name>`.

    Whether `selected`/`picks` values name a real vendor is not checked here: vendors
    are known only when the spreads are built."""
    packages = config["work_packages"]
    items = config.get("items") or []
    item_nos = {str(i["item_no"]) for i in items}
    by_name: dict[str, dict] = {}
    names = set()
    for pkg in packages:
        name = pkg["name"]
        folded = name.strip().casefold()
        if folded in names:
            raise ValueError(f"work_packages: duplicate package name '{name}'")
        names.add(folded)
        by_name[name] = pkg
    for name, pkg in by_name.items():
        listed = {str(n) for n in pkg["items"]}
        for n in pkg["items"]:
            if str(n) not in item_nos:
                raise ValueError(f"work_packages[{name}].items: item '{n}' is not in the spec")
        for n in pkg.get("picks") or {}:
            if str(n) not in listed:
                raise ValueError(f"work_packages[{name}].picks: item '{n}' is not in the package")
        for key in pkg.get("carry") or {}:
            _check_carry_key(name, str(key), listed, items)
    for item in items:
        n = str(item["item_no"])
        for block in item.get("labor") or []:
            for i, line in enumerate(block.get("lines") or []):
                ref = line.get("package")
                if ref is None:
                    continue
                where = f"items[{n}].labor[{block.get('slot')}].lines[{i}].package"
                if ref not in by_name:
                    raise ValueError(f"{where}: '{ref}' is not a work package")
                if n not in {str(x) for x in by_name[ref]["items"]}:
                    raise ValueError(f"{where}: package '{ref}' does not list item '{n}'")
