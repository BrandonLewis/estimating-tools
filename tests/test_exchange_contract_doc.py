"""docs/estimate-exchange-contract.md against what is built: BidSheet.ai's op
tables at the commit it names (docs/estimate-exchange-contract/server-tables.json,
a snapshot regenerated from BidSheet.ai's source by a maintainers' script that
is not part of the public distribution), the golden change sets beside it, and this package's own
constants. The document describes what is built; a failure here means one of
them changed and the document has not caught up (contract part 6). Tables the
tests read are introduced by an HTML comment, ``<!-- table: name -->``."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "estimate-exchange-contract.md"
CONTRACT = ROOT / "docs" / "estimate-exchange-contract"
TABLES = CONTRACT / "server-tables.json"
PYPROJECT = ROOT / "packages" / "estimating-tools" / "pyproject.toml"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _tables() -> dict:
    return json.loads(TABLES.read_text(encoding="utf-8"))


def table(name: str, text: str | None = None) -> list:
    """The rows (header and rule dropped) of the table after ``<!-- table: name -->``.
    Only blank lines may come between the marker and the table."""
    lines = (_text() if text is None else text).splitlines()
    marker = f"<!-- table: {name} -->"
    assert marker in lines, f"the document has no {marker}"
    rows = []
    for line in lines[lines.index(marker) + 1:]:
        if not line.startswith("|"):
            if rows:
                break
            if line.strip():
                raise AssertionError(f"{marker} is not followed by a table")
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if all(c and set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    assert len(rows) > 1, f"table {name} has no rows"
    return rows[1:]


def names(cell: str) -> set:
    """Every backticked name in a cell or a line."""
    return set(re.findall(r"`([^`]+)`", cell))


def section(number: int) -> str:
    """The text of part ``number``, from its ``## N.`` heading to the next ``## ``."""
    match = re.search(rf"^## {number}\. .*?$(.*?)(?=^## |\Z)", _text(), re.M | re.S)
    assert match, f"the document has no part {number}"
    return match.group(1)


def test_a_marker_must_be_followed_by_its_table():
    good = "<!-- table: t -->\n\n| A | B |\n|---|---|\n| 1 | 2 \\| 3 |\n| 4 | 5\n"
    assert table("t", good) == [["1", "2 \\| 3"], ["4", "5"]]
    stray = "<!-- table: t -->\nprose where the table was\n\n| A |\n|---|\n| 1 |\n"
    try:
        table("t", stray)
    except AssertionError as err:
        assert "is not followed by a table" in str(err)
    else:
        raise AssertionError("a marker followed by prose read the next table")


def _version(text: str) -> tuple:
    return tuple(int(p) for p in text.split("."))


def test_the_server_tables_hold_the_catalogue_the_document_describes():
    t = _tables()
    assert len(t["ops"]) == 23
    assert t["max_ops"] == 5000
    assert re.fullmatch(r"[0-9a-f]{40}", t["bidmanager_commit"])


def test_the_header_states_the_version_and_what_it_was_verified_against():
    from estimating_tools.exchange import stamp

    text = _text()
    version = re.search(r"^\*\*Contract version:\*\* (\d+)\.(\d+)$", text, re.M)
    assert version, "no **Contract version:** line"
    assert version.group(1) == stamp.CONTRACT
    verified = re.search(r"^\*\*Verified against:\*\* BidSheet\.ai's server repository "
                         r"\(BidManager\) at commit `([0-9a-f]{40})` on `master`, and "
                         r"estimating-tools (\d+\.\d+\.\d+)\.$", text, re.M)
    assert verified, "no **Verified against:** line naming a 40-character commit and a release"
    assert verified.group(1) == _tables()["bidmanager_commit"]
    package = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert _version(verified.group(2)) <= _version(package)


def test_the_document_names_no_private_design_doc_and_every_path_it_cites_exists():
    text = _text()
    assert "docs/superpowers" not in text
    cited = re.findall(r"`((?:docs|packages|plugins|scripts|tests)/[^`\s]+)`", text)
    assert cited
    for path in cited:
        if any(ch in path for ch in "<>*{}"):
            continue
        assert (ROOT / path).exists(), path


def test_the_transport_table_names_the_client_s_endpoints_and_the_mcp_tools():
    from estimating_tools.exchange import client

    rows = {r[0]: r for r in table("transport")}
    assert set(rows) == {"Read", "Apply"}
    assert "`GET /api/estimates/{id}/workbook/`" in rows["Read"][1]
    assert "`POST /api/estimates/{id}/workbook/apply/`" in rows["Apply"][1]
    assert "`get_estimate_workbook(estimate_id, item_ids=None)`" in rows["Read"][2]
    assert ("`apply_estimate_workbook_changes(estimate_id, ops, dry_run=True, request_id=None)`"
            in rows["Apply"][2])
    assert "`Authorization: Token <token>`" in section(1)
    assert f"at most {client.FETCH_PAGE} ids" in section(1)
    assert "`Idempotency-Key`" in section(1)


#: Part 2's names for kinds whose fingerprint function is named otherwise.
FINGERPRINT_KIND = {"element quantity": "quantity"}


def test_the_identity_table_matches_the_fingerprint_functions_by_kind():
    fingerprints = _tables()["fingerprints"]
    own, borrowed = set(), {}
    for kind_cell, _identity, whose in table("identity"):
        for kind in (k.strip() for k in re.sub(r"\(.*?\)", "", kind_cell).split(",")):
            if whose.startswith("its own"):
                own.add(FINGERPRINT_KIND.get(kind, kind))
            else:
                match = re.fullmatch(r"the (\w+)'s", whose)
                assert match, f"{kind}: {whose!r} names no owner"
                borrowed[kind] = match.group(1)
    assert own == set(fingerprints)
    assert set(borrowed) == {"crew member", "bid total", "estimate input"}
    for kind, owner in borrowed.items():
        assert FINGERPRINT_KIND.get(kind, kind) not in fingerprints, kind
        assert owner in fingerprints, (kind, owner)


def test_part_2_names_the_source_takeover_fields_and_every_section():
    text = section(2)
    for field in ("basis_quantity", "basis_unit", "duration_shifts", "basis_source_measure",
                  "managed_by"):
        assert f"`{field}`" in text, field
    model = json.loads((CONTRACT / "read-model.json").read_text(encoding="utf-8"))
    for key in model:
        assert f"**`{key}`**" in text, key


#: The ``project`` fields BidSheet.ai's read has that ``read-model.json`` lacks:
#: empty while the golden read model is current. Part 2 lists them; when the
#: golden is refreshed and carries them, the test below fails until they are
#: taken out of this set.
PROJECT_FIELDS_NEWER_THAN_GOLDEN = set()


def test_part_2_lists_the_project_fields_as_built():
    listed = re.search(r"`project`\s*\(`\{([^}]*)\}`", section(2))
    assert listed, "part 2 lists no `project` fields"
    fields = {f.strip() for f in listed.group(1).split(",")}
    model = json.loads((CONTRACT / "read-model.json").read_text(encoding="utf-8"))
    golden = set(model["estimate"]["project"])
    assert not golden & PROJECT_FIELDS_NEWER_THAN_GOLDEN, "read-model.json caught up"
    assert fields == golden | PROJECT_FIELDS_NEWER_THAN_GOLDEN
    for name in PROJECT_FIELDS_NEWER_THAN_GOLDEN:
        assert f"`{name}`" in section(6), name


#: Ops whose fields are a structured payload, by the one key each takes.
STRUCTURED_FIELDS = {"bid_totals.set": {"totals"}, "crew.update_members": {"members"}}


def _allowed(t: dict, op: str) -> set:
    if op in t["writable"]:
        return set(t["writable"][op])
    if op == "section.upsert":
        return set(t["section_upsert_fields"])
    return set(STRUCTURED_FIELDS.get(op, set()))


def _placement(t: dict, op: str) -> set:
    return set(t["placement"].get(op, [])) | ({"key"} if op == "element.set_quantity" else set())


def test_the_ops_table_is_bidsheet_s_op_catalogue():
    t = _tables()
    rows = table("ops")
    by_op = {}
    for row in rows:
        found = names(row[0])
        assert len(found) == 1, row
        (op,) = found
        by_op[op] = row
    assert len(by_op) == len(rows)
    assert set(by_op) == set(t["ops"])
    for op, (_op, kind, v, writable, placement, _notes) in by_op.items():
        spec = t["ops"][op]
        assert kind == spec["kind"], op
        if spec["creates"]:
            assert v == "never", op
        elif spec["needs_v"]:
            assert v == "required", op
        else:
            assert v not in ("required", "never"), op
        assert names(writable) == _allowed(t, op), op
        assert names(placement) == _placement(t, op), op


def test_the_required_fields_table_covers_bidsheet_s():
    t = _tables()
    rows = {}
    for op_cell, required in table("required"):
        found = names(op_cell)
        assert len(found) == 1, op_cell
        (op,) = found
        rows[op] = names(required)
    assert set(rows) == set(t["required_on_create"])
    for op, required in t["required_on_create"].items():
        assert rows[op] >= set(required), op
        assert rows[op] <= _allowed(t, op) | _placement(t, op), op
    if any(rows[op] - set(required) for op, required in t["required_on_create"].items()):
        # The snapshot holds only the shape check's list; the rest are checked at apply.
        assert "checked when the op is applied" in section(3)


def test_part_3_states_the_token_and_v_forms():
    t = _tables()
    text = section(3)
    assert t["new_token"] == r"^new:[A-Za-z0-9_.-]{1,64}$"
    assert "1 to 64 letters, digits, `_`, `.` or `-`" in text
    assert t["v_pattern"] == r"^[0-9a-f]{16}$"
    assert "16 hex" in text
    assert f"{t['max_ops']:,} ops" in text
    limits = t["request_id"]
    assert f"1 to {limits['max_length']} of" in text
    assert f"for {limits['retention_hours']} hours" in text


def test_part_4_numbers_the_fourteen_rules():
    text = section(4)
    assert [int(n) for n in re.findall(r"^(\d+)\. ", text, re.M)] == list(range(1, 15))
    for field in ("labor_rate_id", "equipment_rate_id", "material_cost_id", "request_id"):
        assert f"`{field}`" in text, field


def _rule(n: int) -> str:
    match = re.search(rf"^{n}\. (.*)$", section(4), re.M)
    assert match, f"part 4 has no rule {n}"
    return match.group(1)


def test_rule_11_is_the_reader_s_rule():
    from estimating_tools.exchange.reader import ops

    # The reader compares every bound input but these (``keeps_link``).
    free = " and ".join(f.replace("_", " ") for f in ops.LINK_FREE)
    assert ops.LINK_FREE == ("quantity",)
    assert f"every input it binds on the row, bar the {free}, equals its source's" in _rule(11)
    assert "does not bind is carried from the source" in _rule(11)


def _position() -> str:
    """Part 3's Position rule, its sub-bullets and all, as one line."""
    match = re.search(r"^- \*\*Position\.\*\*(.*?)(?=^- |^\S|^\s*$|\Z)", section(3),
                      re.M | re.S)
    assert match, "part 3 has no Position rule"
    return " ".join(match.group(1).split())


def test_position_names_the_ops_that_place_a_create_and_renumber_a_sibling():
    from estimating_tools.exchange.reader import ops

    t, text = _tables(), _position()
    placed = {op for op, fields in t["writable"].items()
              if "sort_order" in fields and t["ops"][op]["creates"]}
    assert placed == {"activity.create", "resource.create"}
    assert "sort_order" not in t["writable"]["step.add"]
    # Every op a golden sends a sort_order on is one the rule names.
    sent = {op["op"] for _n, _i, op in _golden_ops() if "sort_order" in (op.get("fields") or {})}
    assert sent and sent <= names(text), sent - names(text)
    assert placed | {"activity.update", "resource.update", "step.add"} <= names(text)
    assert "ties with the one before" in text and "stopping where a gap opens" in text
    # The renumbering of an allocation-posted line is refused, not sent.
    assert "can't be renumbered" in ops.MANAGED_ORDER
    assert "managed line (rule 6) that would need renumbering is never written" in text
    assert "a row the user moved within its block is not sent" in text
    assert "or a row the surface renumbers to place a create (part 3, Position)" in _rule(3)


def _placed(orders, at):
    """The ``sort_order`` the reader gives a row created at sheet position
    ``at`` (0: above every sibling) among existing siblings ``orders``."""
    from types import SimpleNamespace as NS

    from estimating_tools.exchange.reader import place

    sibs = [(NS(row=10 * (i + 1)), NS(id=i + 1, sort_order=o)) for i, o in enumerate(orders)]
    new, out = object(), place.Orders()
    place.place(sibs, [(new, 10 * at + 5)], out)
    return out.orders[id(new)]


#: Position's placement clauses, as the document and the compact copy word
#: them: a create after the sibling it follows, and one that goes first. The
#: third, a create alone in its block, is worded the same in both
#: (``POSITION_ALONE``, after the order it takes).
POSITION_FOLLOWS = {"doc": "takes the `sort_order` of the existing sibling it follows",
                    "copy": "carries the `sort_order` of the sibling it follows"}
POSITION_FIRST = {"doc": "{offset} the first sibling's when it goes first",
                  "copy": "{offset} the first's when it goes first"}
POSITION_ALONE = "when its block has no existing"
#: How the document words a create's order relative to the first sibling's.
OFFSET_WORDS = {-1: "one less than"}


def _position_clauses(side: str) -> tuple:
    """The three clauses ``side`` must state, with the orders the reader gives."""
    offset = _placed([7, 9], 0) - _placed([7, 9], 1)
    return (POSITION_FOLLOWS[side], POSITION_FIRST[side].format(offset=OFFSET_WORDS[offset]),
            f"{_placed([], 0)} {POSITION_ALONE}")


def test_the_position_clauses_state_the_orders_the_reader_and_the_goldens_send():
    text = _position()
    for clause in _position_clauses("doc"):
        assert clause in text, clause
    # The reader: a create after a sibling takes that sibling's own order.
    assert _placed([7, 9], 1) == 7 and _placed([7, 9], 2) == 9
    # The goldens.
    model = json.loads((CONTRACT / "read-model.json").read_text(encoding="utf-8"))
    res = {(r["activity_id"], r["name"]): r for r in model["resources"]}
    acts = {a["id"]: a for a in model["activities"]}
    create, _update = json.loads((SCENARIOS / "renumbered-resource.changes.json")
                                 .read_text(encoding="utf-8"))["ops"]
    assert create["fields"]["sort_order"] == res[(2, "Carpenters")]["sort_order"]
    ops = json.loads((SCENARIOS / "moved-and-copied-activities.changes.json")
                     .read_text(encoding="utf-8"))["ops"]
    (copy,) = [op for op in ops if op["op"] == "activity.create"]
    assert copy["fields"]["name"] == acts[1]["name"]
    assert copy["fields"]["sort_order"] == acts[1]["sort_order"]
    under = [op for op in ops if op["op"] == "resource.create"
             and op["fields"]["activity_id"] == copy["ref"]]
    assert under and all(op["fields"]["sort_order"] == 0 for op in under)


def test_part_5_states_the_rows_each_op_came_from_as_the_goldens_hold_them():
    text = " ".join(section(5).split())
    assert "`rows`: `{op_index, sheet, row}`, one or more per op" in text
    assert ("a `crew.update_members` lists the member rows its summary names, in sheet order "
            "and each once, then one null row per removed member, never the crew's header row"
            in text)
    nulls = set()
    for path in sorted(SCENARIOS.glob("*.changes.json")):
        golden = json.loads(path.read_text(encoding="utf-8"))
        assert sorted({r["op_index"] for r in golden["rows"]}) == list(range(len(golden["ops"])))
        nulls |= {golden["ops"][r["op_index"]]["op"] for r in golden["rows"] if r["row"] is None}
    assert nulls == {"activity.delete", "resource.delete", "step.delete", "crew.update_members"}


def test_part_6_ties_the_version_to_the_stamp_and_names_the_drift_checks():
    text = " ".join(section(6).split())
    assert "`contract_version`" in text and "BidSheet.ai #1680" in text and "`1.0`" in text
    for check in ("a maintainers' script that is not part of the public distribution",
                  "`tests/test_exchange_contract_doc.py`", "BidSheet.ai's read-back test",
                  "BidSheet.ai's contract test"):
        assert check in text, check


SCENARIOS = CONTRACT / "scenarios"


def _golden_ops() -> list:
    return [(path.name, i, op) for path in sorted(SCENARIOS.glob("*.changes.json"))
            for i, op in enumerate(json.loads(path.read_text(encoding="utf-8"))["ops"])]


def test_every_op_has_a_golden_scenario_or_is_listed_as_having_none():
    t = _tables()
    covered = {op["op"] for _name, _i, op in _golden_ops()}
    line = re.search(r"^\*\*No scenario yet:\*\* (.+?)(?:\n\s*\n|\Z)", section(7), re.M | re.S)
    assert line, "part 7 has no **No scenario yet:** paragraph"
    none_yet = names(line.group(1))
    assert not covered & none_yet, covered & none_yet
    assert covered | none_yet == set(t["ops"])


def test_the_scenario_table_lists_every_golden_with_its_ops():
    listed = {}
    for name_cell, _edit, ops_cell in table("scenarios"):
        (name,) = names(name_cell)
        listed[name] = ops_cell
    by_name = {}
    for p in SCENARIOS.glob("*.json"):
        if not p.name.endswith(".plan.json"):
            by_name.setdefault(p.name.split(".")[0], []).append(p)
    for name, paths in by_name.items():
        assert len(paths) == 1, (name, [p.name for p in paths])
    files = {name: paths[0] for name, paths in by_name.items()}
    assert set(listed) == set(files)
    for name, path in files.items():
        if path.name.endswith(".refused.json"):
            assert listed[name].startswith("refused"), name
            quoted = re.search(r'"([^"]+)"', listed[name])
            assert quoted, f"{name}: the refusal row quotes no reason"
            problems = json.loads(path.read_text(encoding="utf-8"))["problems"]
            assert any(quoted.group(1) in p for p in problems), (name, quoted.group(1))
        else:
            golden = json.loads(path.read_text(encoding="utf-8"))
            ops = {op["op"] for op in golden["ops"]}
            assert names(listed[name]) == ops, name
            if not ops:
                # A scenario that sends nothing quotes the note it reads as.
                assert listed[name].startswith("none: noted"), name
                quoted = re.search(r'"([^"]+)"', listed[name])
                assert quoted, f"{name}: the row quotes no note"
                assert any(quoted.group(1) in n for n in golden["notes"]), name


def test_every_golden_op_is_one_bidsheet_accepts_as_built():
    t = _tables()
    golden = _golden_ops()
    assert len(golden) >= 20
    for name, i, op in golden:
        where = f"{name} op {i}"
        spec = t["ops"][op["op"]]
        fields = set(op.get("fields") or {})
        allowed = _allowed(t, op["op"]) | _placement(t, op["op"])
        assert fields <= allowed, (where, fields - allowed)
        ref = op.get("ref")
        is_new = isinstance(ref, str) and re.match(t["new_token"], ref)
        if spec["creates"] or is_new:
            assert op.get("v") is None, where
        elif spec["needs_v"]:
            assert re.match(t["v_pattern"], op.get("v") or ""), where
        for required in t["required_on_create"].get(op["op"], []):
            assert required in fields, (where, required)


def _class_parts(inner: str) -> list:
    """A regex character class's body as its ranges and single characters, in order."""
    parts, i = [], 0
    while i < len(inner):
        if i + 2 < len(inner) and inner[i + 1] == "-":
            parts.append(inner[i:i + 3])
            i += 3
        else:
            parts.append(inner[i])
            i += 1
    return parts


def _class_in_words(inner: str) -> str:
    """A character class the way the document words it: "letters, digits, `_`, `.` or `-`"."""
    parts = _class_parts(inner)
    words, named = [], set()
    if "A-Z" in parts and "a-z" in parts:
        words.append("letters")
        named |= {"A-Z", "a-z"}
    if "0-9" in parts:
        words.append("digits")
        named.add("0-9")
    words += [f"`{p}`" for p in parts if p not in named]
    if not words:
        raise ValueError(f"empty character class [{inner}]")
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " or " + words[-1]


def test_a_character_class_reads_in_words_whatever_its_size():
    assert _class_in_words("A-Za-z0-9_.-") == "letters, digits, `_`, `.` or `-`"
    assert _class_in_words("_") == "`_`"
    with pytest.raises(ValueError, match="empty character class"):
        _class_in_words("")


def test_the_limits_table_states_the_built_numbers():
    from estimating_tools.exchange import client, stamp
    from estimating_tools.exchange.reader import fields

    t = _tables()
    rows = {limit: value for limit, value, _where in table("limits")}
    assert rows["Ops per apply"] == f"{t['max_ops']:,}"
    low, high = re.search(r"\{(\d+),(\d+)\}\$$", t["new_token"]).groups()
    assert rows["`new:` token"].startswith(f"{low} to {high} ")
    token_class = re.search(r"\[([^\]]+)\]", t["new_token"]).group(1)
    assert f" {_class_in_words(token_class)} after `new:`" in rows["`new:` token"]
    assert rows["`request_id`"].startswith(
        f"1 to {t['request_id']['max_length']} characters of "
        f"`{' '.join(_class_parts(t['request_id']['characters'].strip('[]')))}`,")
    assert rows["`request_id` retention"] == f"{t['request_id']['retention_hours']} hours"
    assert rows["Page size (this client)"] == f"{client.FETCH_PAGE} item ids per read"
    assert rows["Document property"] == "255 characters"
    assert rows["Cell"] == f"{stamp.CELL_LIMIT:,} characters"
    assert rows["Number equality"] == "15 significant digits"
    assert fields._g15(0.1 + 0.2) == "0.3"
    assert fields._g15(1 / 3) == "0." + "3" * 15
    assert rows["Checks tolerance"] == "the pack's, stated per measure"


PACK_YAML = ROOT / "packages/estimating-tools/estimating_tools/heavybook/template/pack.yaml"


def _pack_declaration() -> dict:
    import yaml

    return yaml.safe_load(PACK_YAML.read_text(encoding="utf-8"))


def test_part_5_names_the_stamp_and_the_prototypes_as_the_engine_writes_them():
    from estimating_tools.exchange import baseline, facts, pack, registry, stamp
    from estimating_tools.exchange.reader import book

    text = " ".join(section(5).split())
    assert f"`{stamp.NAME}`" in text
    assert f"`{stamp.PROPERTY}: <pack name> <pack version>`" in text
    assert f"`{stamp.SHEET}!{stamp.CELL}`" in text
    assert f"{baseline.CHUNK:,} characters" in text and f"`{baseline.ENCODING}`" in text
    assert f"`{book.STALE_PROPERTY}`" in text
    assert f"`{registry.PACKS_GROUP}`" in text
    for legacy in facts.DEFAULT_NAMES[1:]:
        assert f"`{legacy}`" in text, legacy
    doc = stamp.make(pack="p", version="1", declaration={}, host="h", estimate_id=1,
                     estimate_v="0" * 16, exported_at="t", baseline={})
    for key in [*doc, "stale"]:
        assert f"`{key}`" in text, key
    for method in ("detect", "build", "read", "patch", "refresh", "templates", "declaration"):
        assert callable(getattr(pack.Pack, method))
        assert f"`{method}`" in text, method
    decl = _pack_declaration()
    assert decl["stamp"] == {"name": stamp.NAME, "sheet": stamp.SHEET, "cell": stamp.CELL,
                             "property": stamp.PROPERTY}
    assert f"`{decl['pack']['name']} {decl['pack']['version']}`" in text
    templates = set(decl["navigator"]["templates"].values())
    assert templates and templates <= set(decl["prototypes"].values())
    listed = {n for n in names(text) if re.fullmatch(r"h[bc]\.(?:tpl|fill)\.[\w.*]+", n)}
    assert {n for n in listed if n.startswith("hc.tpl.")} == templates
    from openpyxl import load_workbook

    defined = set(load_workbook(PACK_YAML.parent / "template.xlsx").defined_names)
    others = listed - templates
    assert others, "part 5 names none of the pack's fill prototypes"
    for name in others:
        assert name.startswith("hb.fill."), name
        if name.endswith("*"):
            assert any(d.startswith(name[:-1]) for d in defined), name
        else:
            assert name in defined, name
    for name in (decl["navigator"]["tables"]["checks"]["name"],
                 decl["navigator"]["cells"]["bid_totals"]):
        assert f"`{name}`" in text, name


def test_part_5_states_heavybook_s_tags_markers_and_owner_formulas_as_built(tmp_path):
    from openpyxl import load_workbook

    from estimating_tools.heavybook.tests import _readback as H

    text = " ".join(section(5).split())
    decl = _pack_declaration()
    sheets = decl["sheets"]
    for sheet in ("cost_report", "crews"):
        for block in sheets[sheet]["blocks"].values():
            for marker in (block.get("marker") or {}).values():
                assert f"`{marker}`" in text, marker
    for role in {s["role"] for s in sheets.values()}:
        assert f"`{role}`" in text, role
    tags = sheets["cost_report"]["tags"]
    assert f"`{tags['owner_row']}`" in text and f"`{tags['parent']['column']}`" in text
    path = H.build_book(json.loads((CONTRACT / "read-model.json").read_text(encoding="utf-8")),
                        tmp_path / "book.xlsx")
    ws = load_workbook(path)[H.CR_TAB]
    r = H.cr_row(ws, "RESOURCE", 1)
    owner, parent = ws[f"{tags['owner_row']}{r}"].value, ws[f"{tags['parent']['column']}{r}"].value
    quoted = re.findall(r"`(=[^`]+)`", text)
    assert [q.replace("<r-1>", str(r - 1)).replace("<r>", str(r)) for q in quoted] == [owner, parent]


SKILL = ROOT / "plugins" / "estimating-core" / "skills" / "apply-estimate-workbook" / "SKILL.md"
PORT = ROOT / "openworker" / "skills" / "apply-estimate-workbook" / "SKILL.md"


def _rules(text: str) -> dict:
    """``{n: text}`` of a numbered list's items, each up to the next item or blank line."""
    return {int(m.group(1)): m.group(2)
            for m in re.finditer(r"^(\d+)\. (.*?)(?=^\d+\. |^\s*$|\Z)", text, re.M | re.S)}


def test_the_skill_and_its_port_carry_a_compact_copy_of_parts_3_and_4():
    t = _tables()
    from estimating_tools.exchange.reader import ops

    free = " and ".join(f.replace("_", " ") for f in ops.LINK_FREE)
    part4 = _rules(section(4))
    rules = list(part4)
    for path in (SKILL, PORT):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^## The exchange contract, in one screen$(.*?)(?=^## |\Z)",
                          text, re.M | re.S)
        assert match, f"{path.relative_to(ROOT)} has no compact copy"
        copy = match.group(1)
        flat = " ".join(copy.split())
        assert "`docs/estimate-exchange-contract.md`" in copy
        version = re.search(r"^\*\*Contract version:\*\* (\d+\.\d+)$", _text(), re.M).group(1)
        assert f"(contract {version})" in flat
        ops = {n for n in names(copy) if re.fullmatch(r"[a-z_]+\.[a-z_]+", n)}
        assert ops == set(t["ops"]), path
        assert f"The {len(t['ops'])} ops" in flat
        assert f"At most {t['max_ops']:,} ops" in flat
        assert f"for {t['request_id']['retention_hours']} hours" in flat
        assert [int(n) for n in re.findall(r"^(\d+)\. ", copy, re.M)] == rules
        for n, rule in _rules(copy).items():
            allowed = names(part4[n]) | names(section(2)) | names(section(3))
            assert names(rule) <= allowed, (path.name, n, names(rule) - allowed)
        assert f"bar its {free}, equals its source's" in " ".join(_rules(copy)[11].split())
        assert "or one renumbered to place a create" in " ".join(_rules(copy)[3].split())
        position = re.search(r"^- Position: (.*?)(?=^- |^\s*$)", copy, re.M | re.S)
        assert position, f"{path.name}: the compact copy has no Position bullet"
        position = " ".join(position.group(1).split())
        assert "`sort_order`" in position and "renumbered" in position
        for clause in _position_clauses("copy"):
            assert clause in position, (path.name, clause)
        assert "refuses the read" in position and "moved within its block is not sent" in position
