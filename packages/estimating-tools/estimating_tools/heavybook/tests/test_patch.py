from __future__ import annotations

import copy
import json
import zipfile
from decimal import Decimal

import pytest

from estimating_tools.exchange.types import ApplyResult
from estimating_tools.exchange import baseline as hb_baseline
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import BF, CR, CW
from estimating_tools.exchange.reader import ReadRefused, run
from estimating_tools.exchange.reader.book import STALE_PROPERTY
from estimating_tools.heavybook.tests import _readback as H


def _pasted_copy(tmp_path):
    """A book where resource 3 (Foreman) is pasted into activity 1's block."""
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    src = H.cr_row(ws, "RESOURCE", 3)
    end = H.block_end(ws, 1)
    H.insert_copies(ws, src, src, end)
    H.save_book(wb, path)
    return path


def _fresh_with_copy():
    fresh = H.fixture_doc()
    new_res = dict(next(r for r in fresh["resources"] if r["id"] == 3))
    new_res.update({"id": 41, "activity_id": 1, "v": "deadbeefdeadbeef"})
    fresh["resources"].append(new_res)
    return fresh


def _plan(result, **extra):
    return ApplyResult.from_plan(
        {"created": {result.change_set.ops[0]["ref"]: "resource:41"}, "deleted": [],
         "totals": {}, **extra}, dry_run=False)


def _parts(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_patch_writes_ids_and_v_and_replaces_the_baseline(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    assert [o["op"] for o in result.change_set.ops] == ["resource.create"]
    (row_map,) = result.change_set.rows
    fresh = _fresh_with_copy()
    before = _parts(path)
    report = p.patch(path, result.change_set, _plan(result), fresh)
    assert report.rows_tagged == 1 and report.baseline_replaced
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    assert ws[f"{CR.ID}{row_map['row']}"].value == 41
    assert ws[f"{CR.V}{row_map['row']}"].value == "deadbeefdeadbeef"
    layout_doc = json.loads(wb["_wb"]["A1"].value)
    chunks = [wb["_wb"].cell(row=r, column=2).value
              for r in range(1, layout_doc["baseline"]["chunks"] + 1)]
    assert hb_baseline.decode(chunks, layout_doc["baseline"]) == fresh
    props = {q.name: q.value for q in wb.custom_doc_props.props}
    assert props["exported_at"] != "2026-10-20T09:00:00Z"
    after = _parts(path)
    changed = H.changed_beyond_cached_values(before, after)
    # The Cost Report, the Checks sheet (its export line), the stamp sheet.
    assert changed <= {"xl/worksheets/sheet3.xml", "xl/worksheets/sheet7.xml",
                       "xl/worksheets/sheet11.xml", "docProps/custom.xml"}


def _baseline_cells(path):
    """``_wb!A1`` and column B as the book holds them."""
    ws = H.open_book(path)["_wb"]
    col_b = []
    for r in range(1, ws.max_row + 1):
        value = ws.cell(row=r, column=2).value
        if value in (None, ""):
            break
        col_b.append(value)
    return ws["A1"].value, col_b


def _no_temp_left(path):
    assert not list(path.parent.glob("*.patching.xlsx"))


def _kept_old_baseline(report):
    """A partial patch's report: the old baseline kept, the verification
    problem last. Returns the problems before it."""
    assert report.baseline_replaced is False
    last = report.problems[-1]
    assert last.startswith("the patched book would not read back clean (")
    assert last.endswith("-- the apply is done; the book keeps its old baseline and is marked "
                         "stale, so every read refuses it; rebuild the book from BidSheet.ai")
    return report.problems[:-1]


def _stale(path):
    """The stale stamp a fallback leaves, and the refusal every read gives."""
    props = {q.name: q.value for q in H.open_book(path).custom_doc_props.props}
    stamp = props[STALE_PROPERTY]
    assert stamp.startswith("applied ") and "not verified" in stamp
    try:
        run(path)
    except ReadRefused as exc:
        (only,) = exc.problems
        assert "could not be patched fully" in only.message
        assert "rebuild the book from BidSheet.ai" in only.message
    else:
        raise AssertionError("a stale book must be refused")
    assert hb_pack.pack().read(path).problems


def test_a_verified_patch_leaves_no_temp_file(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    report = p.patch(path, result.change_set, _plan(result), _fresh_with_copy())
    assert report.baseline_replaced and not report.problems
    _no_temp_left(path)
    props = {q.name: q.value for q in H.open_book(path).custom_doc_props.props}
    assert STALE_PROPERTY not in props


def test_another_users_edit_is_taken_in_even_with_the_old_v(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    (row_map,) = result.change_set.rows
    fresh = _fresh_with_copy()
    # Resource 1 was changed on the server by someone else while this book
    # pasted resource 3, and its v did not move (the contract says a real
    # change always moves it). The merge compares fields whatever v says, so
    # the patch writes their quantity rather than leave the book to send the
    # old one back.
    next(r for r in fresh["resources"] if r["id"] == 1)["quantity"] = "99.000"
    report = p.patch(path, result.change_set, _plan(result), fresh)
    assert report.baseline_replaced and report.problems == []
    assert any("CAT 336" in n and "99" in n for n in report.notes)
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 99
    assert ws[f"{CR.ID}{row_map['row']}"].value == 41
    assert ws[f"{CR.V}{row_map['row']}"].value == "deadbeefdeadbeef"
    _no_temp_left(path)
    again = p.read(path)
    assert not again.problems and again.change_set.ops == []


def test_a_resource_added_on_the_server_meanwhile_is_taken_in(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    fresh = _fresh_with_copy()
    added = dict(next(r for r in fresh["resources"] if r["id"] == 2))
    added.update({"id": 77, "name": "Added on the server", "v": "7777777777777777"})
    fresh["resources"].append(added)
    report = p.patch(path, result.change_set, _plan(result), fresh)
    assert report.baseline_replaced and report.problems == []
    assert any("Added on the server" in n for n in report.notes)
    ws = H.open_book(path)[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 77)
    assert ws[f"{CR.DESC}{row}"].value == "Added on the server"
    assert H.cr_row(ws, "RESOURCE", 41)                       # the apply's own row, tagged
    _no_temp_left(path)
    again = p.read(path)
    assert not again.problems and again.change_set.ops == []


def test_another_users_edit_with_its_new_v_is_taken_in(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    fresh = _fresh_with_copy()
    other = next(r for r in fresh["resources"] if r["id"] == 1)
    other.update({"quantity": "99.000", "v": "9999999999999999"})
    report = p.patch(path, result.change_set, _plan(result), fresh)
    assert report.baseline_replaced
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 99
    again = p.read(path)
    assert not again.problems and again.change_set.ops == []


def test_another_users_crew_change_meanwhile_marks_the_book_stale(tmp_path):
    # The copy would read back clean (no read sends an activity's crew), but
    # its formulas would still price activity 1 with its old crew.
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    fresh = _fresh_with_copy()
    next(a for a in fresh["activities"] if a["id"] == 1).update(crew_id=2, v="b" * 16)
    before = _baseline_cells(path)
    report = p.patch(path, result.change_set, _plan(result), fresh)
    assert _kept_old_baseline(report) == []
    assert "crew_id" in report.problems[-1]
    # The apply is done: the advice is to rebuild, never to apply again.
    assert "apply this book's edits" not in report.problems[-1]
    assert _baseline_cells(path) == before
    _no_temp_left(path)
    _stale(path)


def test_a_structural_change_meanwhile_still_marks_the_book_stale(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    fresh = _fresh_with_copy()
    item = dict(fresh["items"][0])
    item.update({"id": 6, "item_number": "Z9", "description": "Added on the server",
                 "v": "6666666666666666"})
    fresh["items"].append(item)
    other = next(r for r in fresh["resources"] if r["id"] == 1)
    other.update({"quantity": "99.000", "v": "9999999999999999"})
    before = _baseline_cells(path)
    report = p.patch(path, result.change_set, _plan(result), fresh)
    assert _kept_old_baseline(report) == []
    assert _baseline_cells(path) == before
    _no_temp_left(path)
    _stale(path)


def test_a_failing_verification_read_removes_the_temp_and_writes_nothing(tmp_path, monkeypatch):
    from estimating_tools.exchange import reader

    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    real_run, calls = reader.run, []

    def run(book, pack=None):
        calls.append(book)
        if len(calls) == 2:          # the verification read, after the patch's own re-read
            raise RuntimeError("boom")
        return real_run(book, pack=pack)

    monkeypatch.setattr(reader, "run", run)
    before = path.read_bytes()
    try:
        p.patch(path, result.change_set, _plan(result), _fresh_with_copy())
    except RuntimeError:
        pass
    else:
        raise AssertionError("the verification read's error must propagate")
    assert len(calls) == 2
    assert path.read_bytes() == before
    _no_temp_left(path)


def test_patched_book_reads_back_with_no_changes(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    p.patch(path, result.change_set, _plan(result), _fresh_with_copy())
    again = p.read(path)
    assert not again.problems and again.change_set.ops == []


def test_patch_prefers_the_servers_versions(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    (row_map,) = result.change_set.rows
    p.patch(path, result.change_set, _plan(result, versions={"resource:41": "0123456789abcdef"}),
            _fresh_with_copy())
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.V}{row_map['row']}"].value == "0123456789abcdef"


def test_patch_refuses_a_dry_run_result(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    result = p.read(path)
    try:
        p.patch(path, result.change_set,
                ApplyResult.from_plan({"created": {}, "deleted": [], "totals": {}}, dry_run=True),
                H.fixture_doc())
    except ValueError as exc:
        assert "dry run" in str(exc)
    else:
        raise AssertionError("a dry run must not patch")


def test_update_refreshes_v(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e2.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 3)
    old_v = ws[f"{CR.V}{row}"].value
    ws[f"{CR.QTY}{row}"] = 9
    H.save_book(wb, path)
    p = hb_pack.pack()
    result = p.read(path)
    assert [o["op"] for o in result.change_set.ops] == ["resource.update"]
    fresh = H.fixture_doc()
    next(r for r in fresh["resources"] if r["id"] == 3)["v"] = "feedfacefeedface"
    report = p.patch(path, result.change_set,
                     ApplyResult.from_plan({"created": {}, "deleted": [], "totals": {}},
                                           dry_run=False), fresh)
    assert report.rows_tagged == 1
    ws = H.open_book(path)[H.CR_TAB]
    assert old_v != "feedfacefeedface"
    assert ws[f"{CR.V}{row}"].value == "feedfacefeedface"
    assert ws[f"{CR.ID}{row}"].value == 3


def test_delete_tags_nothing_but_replaces_the_baseline(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e3.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 3)
    ws.delete_rows(row)
    H.save_book(wb, path)
    p = hb_pack.pack()
    result = p.read(path)
    assert [o["op"] for o in result.change_set.ops] == ["resource.delete"]
    fresh = H.fixture_doc()
    fresh["resources"] = [r for r in fresh["resources"] if r["id"] != 3]
    report = p.patch(path, result.change_set,
                     ApplyResult.from_plan({"created": {}, "deleted": ["resource:3"],
                                            "totals": {}}, dry_run=False), fresh)
    assert report.rows_tagged == 0 and report.baseline_replaced
    wb = H.open_book(path)
    layout_doc = json.loads(wb["_wb"]["A1"].value)
    chunks = [wb["_wb"].cell(row=r, column=2).value
              for r in range(1, layout_doc["baseline"]["chunks"] + 1)]
    assert hb_baseline.decode(chunks, layout_doc["baseline"]) == fresh


# -- a stand-in for BidSheet.ai: what the apply leaves behind ---------------------

def _v(ident):
    return f"{ident:016x}"


def _server(doc, cs, start=50, keep_library=False):
    """``(fresh payload, plan)`` after applying ``cs`` to ``doc`` the way
    BidSheet.ai does: creates get the next ids in op order; a crew's roster
    is deleted and recreated (every member gets a new id, in roster order);
    an edited library crew is copied into the estimate (``crew:<old>`` in
    ``created``) and its activities repointed, unless ``keep_library``."""
    fresh, created = copy.deepcopy(doc), {}
    ids = iter(range(start, start + 1000))
    acts = {a["id"]: a for a in fresh["activities"]}

    def resolve(ref):
        return created[ref] if isinstance(ref, str) and ref.startswith("new:") else ref

    def source(rows, name):
        return next((r for r in rows if r["name"] == name), None)

    for op in cs.ops:
        name, f = op["op"], op["fields"]
        if name == "activity.create":
            new = copy.deepcopy(source(doc["activities"], f["name"]) or acts[1])
            new.update({k: v for k, v in f.items() if k not in ("parent_id", "estimate_item_id")})
            new.update(id=next(ids), parent_id=resolve(f.get("parent_id")), steps=[],
                       estimate_item_id=f["estimate_item_id"], crew_id=None)
            new["v"] = _v(new["id"])
            fresh["activities"].append(new)
            acts[new["id"]] = new
            created[op["ref"]] = new["id"]
        elif name in ("activity.update", "activity.set_crew"):
            a = acts[resolve(op["ref"])]
            a.update(f)
            a["v"] = _v(a["id"] + 500)
        elif name == "step.add":
            a = acts[resolve(f["activity_id"])]
            step = {"id": next(ids), "name": f["name"], "duration": f["duration"],
                    "duration_unit": f["duration_unit"], "sort_order": len(a["steps"]),
                    "activity_code_id": None}
            step["v"] = _v(step["id"])
            a["steps"].append(step)
            created[op["ref"]] = step["id"]
        elif name == "resource.create":
            res = copy.deepcopy(source(doc["resources"], f["name"]) or {
                "activity_code_id": None, "burden_percentage": None, "cost": "0",
                "description": "", "equipment_rate_id": None, "includes_burden": False,
                "labor_cost_basis": "production", "labor_rate_id": None, "managed_by": None,
                "material_cost_id": None, "parent_component_id": None, "pieces": None,
                "sort_order": 0, "time_unit": "", "time_value": None, "trade": "",
                "unit": "", "unit_cost": None, "quantity": None})
            res.update({k: v for k, v in f.items() if k != "activity_id"})
            res.update(id=next(ids), activity_id=resolve(f["activity_id"]))
            res["v"] = _v(res["id"])
            fresh["resources"].append(res)
            created[op["ref"]] = res["id"]
        elif name == "resource.update":
            res = next(r for r in fresh["resources"] if r["id"] == op["ref"])
            res.update(f)
            res["v"] = _v(res["id"] + 500)
        elif name == "crew.update_members":
            crew = next(c for c in fresh["crews"] if c["id"] == op["ref"])
            if crew["scope"] == "library":
                copied = copy.deepcopy(crew)
                copied.update(id=next(ids), scope="estimate")
                if not keep_library:
                    fresh["crews"].remove(crew)
                    for a in fresh["activities"]:
                        if a.get("crew_id") == crew["id"]:
                            a["crew_id"] = copied["id"]
                fresh["crews"].append(copied)
                created[f"crew:{crew['id']}"] = copied["id"]
                crew = copied
            members = []
            for m in f["members"]:
                mid = next(ids)
                members.append({"id": mid, "classification": m["classification"],
                                "count": f"{Decimal(m['count']):.2f}",
                                "labor_rate_id": m["labor_rate_id"],
                                "hourly_rate_override": m["hourly_rate_override"],
                                "effective_hourly_rate": m["hourly_rate_override"] or "54.00",
                                "sort_order": m["sort_order"]})
            # The payload's order: (sort_order, classification, id).
            crew["members"] = sorted(members, key=lambda m: (m["sort_order"],
                                                             m["classification"], m["id"]))
            crew["v"] = _v(crew["id"] + 500)
        elif name == "estimate.update":
            fresh["estimate"].update(f)
            fresh["estimate"]["v"] = "e5e5e5e5e5e5e5e5"
    kinds = {"a": "activity", "s": "step", "r": "resource"}
    refs = {}
    for tok, ident in created.items():
        kind = "crew" if tok.startswith("crew:") else kinds[tok[4]]
        refs[tok] = f"{kind}:{ident}"
    plan = ApplyResult.from_plan({"created": refs, "deleted": [], "totals": {}},
                                 dry_run=False)
    return fresh, plan


def _patched(path, start=50, doc=None, **kw):
    """Read ``path``, apply it on the stand-in server, patch. Returns
    ``(first read, fresh payload, report)``."""
    p = hb_pack.pack()
    first = p.read(path)
    assert not first.problems, first.problems
    fresh, plan = _server(doc or H.fixture_doc(), first.change_set, start=start, **kw)
    report = p.patch(path, first.change_set, plan, fresh)
    return first, fresh, report


def _clean(path):
    again = hb_pack.pack().read(path)
    assert not again.problems, again.problems
    assert again.change_set.ops == [], again.change_set.ops
    return again


def _edit(path, sheet, ref, value):
    wb = H.open_book(path)
    wb[sheet][ref] = value
    H.save_book(wb, path)
    again = hb_pack.pack().read(path)
    assert not again.problems, again.problems
    return again.change_set.ops


def test_a_pasted_activity_block_is_live_after_the_patch(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "a.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    first, last = H.cr_row(ws, "ACTIVITY", 1), H.block_end(ws, 1)
    H.insert_copies(ws, first, last, last + 1)
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert [o["op"] for o in read.change_set.ops][:1] == ["activity.create"]
    assert not report.problems
    ws = H.open_book(path)[H.CR_TAB]
    block = range(last + 1, last + 1 + (last - first + 1))
    assert ws[f"{CR.ID}{last + 1}"].value == 50
    # The block's rows keep their owner chain (the copy brought it), which
    # now names the new activity; the patch wrote no owner tag.
    assert all(ws[f"{CR.PARENT}{r}"].value == H.owner_formula(r) for r in block if r != last + 1)
    _clean(path)
    res_row = next(r for r in block if ws[f"{CR.KIND}{r}"].value == "RESOURCE")
    ops = _edit(path, H.CR_TAB, f"{CR.QTY}{res_row}", 77)
    assert [(o["op"], o["ref"]) for o in ops] == [("resource.update", 51)]


def test_a_copied_parent_with_its_child_points_the_child_at_the_new_parent(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "a.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    first, last = H.cr_row(ws, "ACTIVITY", 2), H.block_end(ws, 3)
    H.insert_copies(ws, first, last, last + 1)
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    creates = [o for o in read.change_set.ops if o["op"] == "activity.create"]
    assert creates[1]["fields"]["parent_id"] == creates[0]["ref"]
    assert not report.problems
    ws = H.open_book(path)[H.CR_TAB]
    child = H.cr_row(ws, "ACTIVITY", 51)
    assert ws[f"{CR.PARENT}{child}"].value == 50          # stored: the tree parent
    end = H.block_end(ws, 51)
    assert ws[f"{CR.PARENT}{end}"].value == H.owner_formula(end)
    _clean(path)


def _member_rows(ws, crew_id):
    head = H.cw_row(ws, "CREW", crew_id)
    end = H.cw_row(ws, "CREW_END", parent=crew_id)
    return [r for r in range(head, end) if ws[f"{CW.KIND}{r}"].value == "MEMBER"]


def test_an_edited_estimate_crew_takes_its_renumbered_members(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    ws[f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', 2, parent=1)}"] = 5
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert [o["op"] for o in read.change_set.ops] == ["crew.update_members"]
    assert not report.problems
    ws = H.open_book(path)[H.CW_TAB]
    assert [ws[f"{CW.ID}{r}"].value for r in _member_rows(ws, 1)] == [50, 51]
    _clean(path)
    ops = _edit(path, H.CW_TAB, f"{CW.COUNT}{_member_rows(ws, 1)[0]}", 3)
    assert [(o["op"], o["ref"]) for o in ops] == [("crew.update_members", 1)]


LIBRARY_BANNER = "Library crew -- an edit copies it into this estimate."


def test_an_edited_library_crew_becomes_its_estimate_copy(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    ws[f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', 3, parent=2)}"] = 5
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert [(o["op"], o["ref"]) for o in read.change_set.ops] == [("crew.update_members", 2)]
    assert not report.problems
    ws = H.open_book(path)[H.CW_TAB]
    head = H.cw_row(ws, "CREW", 50)
    end = H.cw_row(ws, "CREW_END", parent=50)
    assert [ws[f"{CW.ID}{r}"].value for r in _member_rows(ws, 50)] == [51]
    assert all(ws[f"{CW.CREW}{r}"].value == H.crew_formula(r) for r in _member_rows(ws, 50))
    # An estimate crew carries no library banner.
    assert all(ws[f"{CW.KIND}{r}"].value != "NOTE" for r in range(head, end))
    assert all(ws[f"{CW.NAME}{r}"].value != LIBRARY_BANNER for r in range(head, end))
    _clean(path)
    ops = _edit(path, H.CW_TAB, f"{CW.COUNT}{_member_rows(ws, 50)[0]}", 2)
    assert [(o["op"], o["ref"]) for o in ops] == [("crew.update_members", 50)]


def test_a_library_crew_the_payload_still_lists_is_a_problem(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    ws[f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', 3, parent=2)}"] = 5
    H.save_book(wb, path)
    before = _baseline_cells(path)
    read, fresh, report = _patched(path, keep_library=True)
    (only,) = _kept_old_baseline(report)
    assert "Pour crew" in only and "rebuild the book" in only
    assert _baseline_cells(path) == before
    _no_temp_left(path)
    _stale(path)      # refused, never a duplicate push


def test_an_added_member_leaves_no_spurious_roster_op(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    src = H.cw_row(ws, "MEMBER", 2, parent=1)
    end = H.cw_row(ws, "CREW_END", parent=1)
    H.insert_copies(ws, src, src, end)
    ws[f"{CW.COUNT}{end}"] = 4
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert not report.problems
    ws = H.open_book(path)[H.CW_TAB]
    assert [ws[f"{CW.ID}{r}"].value for r in _member_rows(ws, 1)] == [50, 51, 52]
    _clean(path)
    ops = _edit(path, H.CW_TAB, f"{CW.COUNT}{_member_rows(ws, 1)[2]}", 6)
    assert [(o["op"], o["ref"]) for o in ops] == [("crew.update_members", 1)]


def test_a_typed_member_row_is_matched_and_gets_its_formulas(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    end = H.cw_row(ws, "CREW_END", parent=1)
    H.type_row(ws, end, {CW.CODE: "Laborer", CW.COUNT: 1, CW.OVERRIDE: 45})
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert not report.problems
    ws = H.open_book(path)[H.CW_TAB]
    assert ws[f"{CW.KIND}{end}"].value == "MEMBER" and ws[f"{CW.ID}{end}"].value == 52
    assert ws[f"{CW.EXTENDED}{end}"].value == f"={CW.COUNT}{end}*{CW.EFFECTIVE}{end}"
    assert ws[f"{CW.CREW}{end}"].value == H.crew_formula(end)    # the prototype's chain
    _clean(path)


def test_unmatched_member_rows_are_a_problem_and_left_alone(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    ws[f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', 2, parent=1)}"] = 5
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    fresh, plan = _server(H.fixture_doc(), read.change_set)
    crew = next(c for c in fresh["crews"] if c["id"] == 1)
    crew["members"][0]["classification"] = "Somebody else"
    report = p.patch(path, read.change_set, plan, fresh)
    assert _kept_old_baseline(report) == [
        "Crews rows 6-7: crew Excavation crew's member rows could not be matched to "
        "BidSheet.ai's -- rebuild the book from BidSheet.ai"]
    ws = H.open_book(path)[H.CW_TAB]
    assert [ws[f"{CW.ID}{r}"].value for r in _member_rows(ws, 1)] == [1, 2]


def test_a_typed_resource_row_gets_its_kind_and_formulas(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "t.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.block_end(ws, 1)
    H.type_row(ws, row, {CR.DESC: "Typed line", CR.QTY: 3, CR.UNIT: "HR", CR.UCOST: 40,
                         CR.TYPE: "labor"})
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert [o["op"] for o in read.change_set.ops] == ["resource.create"]
    assert not report.problems
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.KIND}{row}"].value == "RESOURCE" and ws[f"{CR.ID}{row}"].value == 50
    assert ws[f"{CR.PARENT}{row}"].value == H.owner_formula(row)    # the prototype's chain
    assert ws[f"{CR.TOTAL}{row}"].value == f"={CR.H2}{row}"
    assert ws[f"{CR.ACT}{row}"].value == (f'=IF({CR.KIND}{row}="ACTIVITY",ROW(),'
                                          f'MAX({CR.ACT}$4:{CR.ACT}{row - 1}))')
    assert ws[f"{CR.DESC}{row}"].value == "Typed line"     # typed values left alone
    _clean(path)
    ops = _edit(path, H.CR_TAB, f"{CR.QTY}{row}", 5)
    assert [(o["op"], o["ref"]) for o in ops] == [("resource.update", 50)]


def test_a_typed_step_row_gets_its_kind_and_tag(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "t.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    start = H.cr_row(ws, "START", parent=4)
    H.type_row(ws, start, {CR.DESC: "Typed step", CR.QTY: 2, CR.UNIT: "DAYS"})
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert [o["op"] for o in read.change_set.ops] == ["step.add"]
    assert not report.problems
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.KIND}{start}"].value == "STEP" and ws[f"{CR.ID}{start}"].value == 50
    assert ws[f"{CR.CODE}{start}"].value == "step"
    assert ws[f"{CR.PARENT}{start}"].value == H.owner_formula(start)
    _clean(path)


def test_a_new_prototype_activity_takes_the_servers_defaults(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "n.xlsx")
    wb = H.open_book(path)
    at = H.cr_row(wb[H.CR_TAB], "ITEM", 4)
    H.insert_template(wb, "hc.tpl.activity", H.CR_TAB, at)
    ws = wb[H.CR_TAB]
    ws[f"{CR.DESC}{at}"] = "Haul"
    ws[f"{CR.SHIFTS}{at}"] = 2
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    assert not read.problems, read.problems
    assert [o["op"] for o in read.change_set.ops][0] == "activity.create"
    fresh, plan = _server(H.fixture_doc(), read.change_set)
    new = next(a for a in fresh["activities"] if a["id"] == 50)
    new.update(hours_per_shift="8.0", crew_factor="1.000", count=1, production_rate=None,
               production_unit="DAYS", name="Haul", duration_shifts="2.00")
    report = p.patch(path, read.change_set, plan, fresh)
    assert not report.problems
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.ID}{at}"].value == 50
    assert ws[f"{CR.HPS}{at}"].value == 8          # the server's default, shown
    end = H.block_end(ws, 50)
    assert ws[f"{CR.PARENT}{end}"].value == H.owner_formula(end)
    _clean(path)


def test_an_estimate_update_tags_the_estimate_row(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e.xlsx")
    wb = H.open_book(path)
    ws = wb[H.BF_TAB]
    amount, pct = BF.ROWS["markup_amount"], BF.ROWS["markup_percentage"]
    ws[f"{BF.VALUE}{amount}"] = 999
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert [o["op"] for o in read.change_set.ops] == ["estimate.update"]
    ws = H.open_book(path)[H.BF_TAB]
    assert ws[f"{BF.V}{pct}"].value == "e5e5e5e5e5e5e5e5"
    assert ws[f"{BF.V}{amount}"].value is None
    assert report.rows_tagged == 1
    _clean(path)


def test_element_set_quantity_prefers_the_servers_version(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "q.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "ELEMENT_QTY")
    element = ws[f"{CR.ID}{row}"].value
    ws[f"{CR.QTY}{row}"] = 12
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    assert [o["op"] for o in read.change_set.ops] == ["element.set_quantity"]
    plan = ApplyResult.from_plan({"created": {}, "deleted": [], "totals": {},
                                  "versions": {f"element:{element}": "abcabcabcabcabca"}},
                                 dry_run=False)
    p.patch(path, read.change_set, plan, H.fixture_doc())
    assert H.open_book(path)[H.CR_TAB][f"{CR.V}{row}"].value == "abcabcabcabcabca"


def test_a_patch_leaves_every_formula_cached_with_current_values(tmp_path):
    # The edit is saved through openpyxl, which drops every cached value; the
    # patch must put back values computed from the patched book (#370).
    import datetime as dt

    from openpyxl import load_workbook
    from openpyxl.utils.datetime import to_excel

    from estimating_tools.xlcalc.book import Book
    from estimating_tools.xlcalc.evaluate import Failed, evaluate
    from estimating_tools.xlcalc.values import Err

    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE')}"] = 12
    H.save_book(wb, path)
    first, _fresh, report = _patched(path)
    assert first.change_set.ops and report.baseline_replaced, report.problems
    cached = load_workbook(path, data_only=True)
    fresh = evaluate(Book.load(path))
    assert fresh and not [k for k, v in fresh.items() if isinstance(v, Failed)]
    wrong = []
    for (sheet, r, c), want in fresh.items():
        got = cached[sheet].cell(r, c).value
        if isinstance(got, (dt.datetime, dt.date)):
            got = to_excel(got)
        if isinstance(want, Err):
            want = want.code
        if want == "" and got is None:
            continue
        if isinstance(want, float) and isinstance(got, (int, float)) \
                and not isinstance(got, bool) and abs(got - want) <= 1e-9 * max(1.0, abs(want)):
            continue
        if got != want:
            wrong.append((sheet, r, c, got, want))
    assert not wrong, wrong[:10]


def test_a_book_changed_since_the_read_is_refused(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "x.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 3)}"] = 9
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    wb = H.open_book(path)
    H.type_row(wb[H.CR_TAB], 6, {CR.DESC: "x"})
    H.save_book(wb, path)
    before = path.read_bytes()
    fresh, plan = _server(H.fixture_doc(), read.change_set)
    try:
        p.patch(path, read.change_set, plan, fresh)
    except ValueError as exc:
        assert "changed since" in str(exc)
    else:
        raise AssertionError("a book edited after the read must not be patched")
    assert path.read_bytes() == before


def _save_during_verification(monkeypatch, path):
    """A save to the book while the patch's copy is being read back."""
    from estimating_tools.exchange.patch import verify

    real = verify.unclean

    def unclean(tmp, pack):
        why = real(tmp, pack)
        wb = H.open_book(path)
        H.type_row(wb[H.CR_TAB], 6, {CR.DESC: "typed during the patch"})
        H.save_book(wb, path)
        return why

    monkeypatch.setattr(verify, "unclean", unclean)


def test_a_save_during_the_verification_read_is_not_overwritten(tmp_path, monkeypatch):
    path = H.build_book(H.fixture_doc(), tmp_path / "x.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 3)}"] = 9
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    fresh, plan = _server(H.fixture_doc(), read.change_set)
    _save_during_verification(monkeypatch, path)
    with pytest.raises(ValueError, match="changed since"):
        p.patch(path, read.change_set, plan, fresh)
    wb = H.open_book(path)
    assert wb[H.CR_TAB][f"{CR.DESC}6"].value == "typed during the patch"
    assert not list(tmp_path.glob("*.patching.xlsx"))
    assert STALE_PROPERTY not in {q.name for q in wb.custom_doc_props.props}


def test_a_save_during_an_unclean_verification_is_not_patched_either(tmp_path, monkeypatch):
    path = H.build_book(H.fixture_doc(), tmp_path / "x.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 3)}"] = 9
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    fresh, plan = _server(H.fixture_doc(), read.change_set)
    next(r for r in fresh["resources"] if r["id"] == 1)["quantity"] = "77.000"  # another user
    _save_during_verification(monkeypatch, path)
    with pytest.raises(ValueError, match="changed since"):
        p.patch(path, read.change_set, plan, fresh)
    wb = H.open_book(path)
    assert wb[H.CR_TAB][f"{CR.DESC}6"].value == "typed during the patch"
    assert STALE_PROPERTY not in {q.name for q in wb.custom_doc_props.props}


def test_member_ids_follow_creation_order_not_the_payloads_sort(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    # Renamed past OPER: the payload now lists OPER (id 51) before it (id 50).
    ws[f"{CW.CODE}{H.cw_row(ws, 'MEMBER', 1, parent=1)}"] = "Zed laborer"
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    crew = next(c for c in fresh["crews"] if c["id"] == 1)
    assert [m["id"] for m in crew["members"]] == [51, 50]
    assert not report.problems
    ws = H.open_book(path)[H.CW_TAB]
    rows = _member_rows(ws, 1)
    assert [(ws[f"{CW.CODE}{r}"].value, ws[f"{CW.ID}{r}"].value) for r in rows] == [
        ("Zed laborer", 50), ("OPER", 51)]
    _clean(path)


def test_member_ids_the_plan_returns_win_over_the_inference(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    ws[f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', 2, parent=1)}"] = 5
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    fresh, _plan = _server(H.fixture_doc(), read.change_set)
    crew = next(c for c in fresh["crews"] if c["id"] == 1)
    # The server numbered the roster backwards: Laborer 61, OPER 60.
    for m in crew["members"]:
        m["id"] = 61 if m["classification"] == "Laborer" else 60
    plan = ApplyResult.from_plan(
        {"created": {}, "deleted": [], "totals": {},
         "ops": [{"index": 0, "after": {"members": [{"id": 61}, {"id": 60}]}}]},
        dry_run=False)
    report = p.patch(path, read.change_set, plan, fresh)
    assert not report.problems
    ws = H.open_book(path)[H.CW_TAB]
    assert [ws[f"{CW.ID}{r}"].value for r in _member_rows(ws, 1)] == [61, 60]
    _clean(path)


def _two_opers():
    """Crew 1 with two OPER members of count 1 on different labour rates."""
    doc = H.fixture_doc()
    doc["rates"]["labor"].append({"classification": "OPER", "id": 2, "rate": "60.00",
                                  "unit": "HR"})
    crew = next(c for c in doc["crews"] if c["id"] == 1)
    crew["members"].append({"classification": "OPER", "count": "1.00",
                            "effective_hourly_rate": "60.00", "hourly_rate_override": None,
                            "id": 5, "labor_rate_id": 2, "sort_order": 0})
    return doc


def test_members_alike_but_for_their_rate_are_not_swapped(tmp_path):
    doc = _two_opers()
    path = H.build_book(doc, tmp_path / "c.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CW_TAB]
    ws[f"{CW.COUNT}{H.cw_row(ws, 'MEMBER', 1, parent=1)}"] = 3
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    rates = [m["labor_rate_id"] for m in read.change_set.ops[0]["fields"]["members"]]
    assert rates == [None, 1, 2]
    fresh, plan = _server(doc, read.change_set)
    crew = next(c for c in fresh["crews"] if c["id"] == 1)
    # Ids that pair the two OPER rows the wrong way round.
    for m in crew["members"]:
        if m["labor_rate_id"] is not None:
            m["id"] = 51 if m["labor_rate_id"] == 2 else 52
    report = p.patch(path, read.change_set, plan, fresh)
    (only,) = _kept_old_baseline(report)
    assert "could not be matched" in only
    ws = H.open_book(path)[H.CW_TAB]
    assert [ws[f"{CW.ID}{r}"].value for r in _member_rows(ws, 1)] == [1, 2, 5]


def _strip_full_calc(path):
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(b' fullCalcOnLoad="1"', b"")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    assert b"fullCalcOnLoad" not in parts["xl/workbook.xml"]


def test_a_patch_that_writes_a_tag_asks_excel_to_recalculate(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "r.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 3)}"] = 9
    H.save_book(wb, path)
    _strip_full_calc(path)
    read, fresh, report = _patched(path)
    assert report.rows_tagged == 1
    assert b'fullCalcOnLoad="1"' in _parts(path)["xl/workbook.xml"]
    _clean(path)


def test_a_baseline_only_patch_leaves_the_workbook_part_alone(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "r.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws.delete_rows(H.cr_row(ws, "RESOURCE", 3))
    H.save_book(wb, path)
    _strip_full_calc(path)
    before = _parts(path)["xl/workbook.xml"]
    p = hb_pack.pack()
    read = p.read(path)
    fresh = H.fixture_doc()
    fresh["resources"] = [r for r in fresh["resources"] if r["id"] != 3]
    report = p.patch(path, read.change_set, ApplyResult.from_plan(
        {"created": {}, "deleted": ["resource:3"], "totals": {}}, dry_run=False), fresh)
    assert report.rows_tagged == 0
    assert _parts(path)["xl/workbook.xml"] == before


def test_a_prototype_constant_never_lands_in_an_input_cell(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "t.xlsx")
    wb = H.open_book(path)
    first, _last = H.template_rows(wb, "hc.tpl.step")
    # A prototype whose duration unit holds a constant: the server's DAYS is
    # what a blank cell reads as, so nothing is filled -- and the prototype's
    # HOURS must not be copied either.
    wb["_templates"][f"{CR.UNIT}{first}"] = "HOURS"
    ws = wb[H.CR_TAB]
    start = H.cr_row(ws, "START", parent=4)
    H.type_row(ws, start, {CR.DESC: "Typed step", CR.QTY: 2})
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert [o["op"] for o in read.change_set.ops] == ["step.add"]
    assert read.change_set.ops[0]["fields"]["duration_unit"] == "DAYS"
    assert not report.problems
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.UNIT}{start}"].value is None
    _clean(path)


def test_a_book_without_the_prototype_says_so_and_still_tags_the_row(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "t.xlsx")
    wb = H.open_book(path)
    del wb.defined_names["hc.tpl.resource"]
    ws = wb[H.CR_TAB]
    row = H.block_end(ws, 1)
    H.type_row(ws, row, {CR.DESC: "Typed line", CR.QTY: 3, CR.UCOST: 40, CR.TYPE: "labor"})
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert _kept_old_baseline(report) == [
        f"Cost Report row {row}: the book has no resource prototype row, so the typed row "
        "has no formulas -- rebuild the book from BidSheet.ai"]
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.KIND}{row}"].value == "RESOURCE" and ws[f"{CR.ID}{row}"].value == 50
    assert hb_pack.pack().read(path).problems    # refused, never created twice


def test_a_value_typed_where_a_formula_belongs_is_a_problem(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "t.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.block_end(ws, 1)
    H.type_row(ws, row, {CR.DESC: "Typed line", CR.QTY: 3, CR.UCOST: 40, CR.TYPE: "labor",
                         CR.TOTAL: 120})
    H.save_book(wb, path)
    read, fresh, report = _patched(path)
    assert _kept_old_baseline(report) == [
        f"Cost Report row {row} column {CR.TOTAL}: a value is typed where a resource row has "
        "a formula -- clear it and copy the formula from a row of the same kind, or rebuild "
        "the book from BidSheet.ai"]
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.TOTAL}{row}"].value == 120 and ws[f"{CR.ID}{row}"].value == 50
    assert ws[f"{CR.MH}{row}"].value == f'=IF({CR.TYPE}{row}="labor",{CR.QTY}{row},0)'


def test_a_created_row_missing_from_the_fresh_estimate_keeps_its_id(tmp_path):
    path = _pasted_copy(tmp_path)
    p = hb_pack.pack()
    read = p.read(path)
    (row_map,) = read.change_set.rows
    report = p.patch(path, read.change_set, _plan(read), H.fixture_doc())
    assert _kept_old_baseline(report) == [
        "resource 41 is not in the fresh estimate, so its row keeps only its id -- rebuild "
        "the book from BidSheet.ai"]
    assert H.open_book(path)[H.CR_TAB][f"{CR.ID}{row_map['row']}"].value == 41


# -- the second review of PR #446: ordinary applies stay adopted ----------------------------

def _copy_block(path, activity):
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    first, last = H.cr_row(ws, "ACTIVITY", activity), H.block_end(ws, activity)
    H.insert_copies(ws, first, last, last + 1)
    H.save_book(wb, path)
    return first


def test_a_copied_activity_is_patched(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    _copy_block(path, 6)
    _read, _fresh, report = _patched(path)
    assert report.baseline_replaced and not report.problems
    _clean(path)


def test_a_copied_activity_and_its_library_crew_edit_are_patched_in_one_apply(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    _copy_block(path, 6)
    wb = H.open_book(path)
    cw = wb[H.CW_TAB]
    cw[f"{CW.COUNT}{H.cw_row(cw, 'MEMBER', 3, parent=2)}"] = 5
    H.save_book(wb, path)
    read, _fresh, report = _patched(path)
    assert ("crew.update_members", 2) in [(o["op"], o["ref"]) for o in read.change_set.ops]
    assert report.baseline_replaced and not report.problems
    _clean(path)


def test_the_apply_restamping_a_copied_rows_source_does_not_make_the_book_stale(tmp_path):
    """A copied stepped activity and an edit to its source's step, in one
    apply: BidSheet.ai restamps the source's duration_shifts and v. The copy
    is the apply's, so that is no "copied" collision."""
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    first = _copy_block(path, 4)
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'STEP', 1, start=first)}"] = 3
    H.save_book(wb, path)
    p = hb_pack.pack()
    read = p.read(path)
    fresh, plan = _server(H.fixture_doc(), read.change_set)
    act = next(a for a in fresh["activities"] if a["id"] == 4)
    for op in read.change_set.ops:
        if op["op"] == "step.update":
            step = next(x for x in act["steps"] if x["id"] == op["ref"])
            step.update(op["fields"])
            step["v"] = "5" * 16
    act.update(duration_shifts="3.00", v="4" * 16)
    report = p.patch(path, read.change_set, plan, fresh)
    assert report.baseline_replaced and not report.problems
    _clean(path)


def _delete_blocks(path, first_activity, last_activity):
    from estimating_tools.exchange import rowops, writer

    ws = H.open_book(path)[H.CR_TAB]
    first, last = H.cr_row(ws, "ACTIVITY", first_activity), H.block_end(ws, last_activity)
    writer.edit(path, rows=[rowops.DeleteRows(sheet=H.CR_TAB, first=first,
                                              count=last - first + 1)],
                lost_ok={"Checks", "Flat", "Recap", "Schedule", "_shares"})


def _without(doc, gone):
    doc["activities"] = [a for a in doc["activities"] if a["id"] not in gone]
    doc["resources"] = [x for x in doc["resources"] if x["activity_id"] not in gone]
    doc["shares"] = [x for x in doc.get("shares", []) if x.get("activity_id") not in gone]
    return doc


@pytest.mark.parametrize("acts, ops", [((2, 3), [("activity.delete", 2)]),
                                       ((3, 3), [("activity.delete", 3)])])
def test_a_deleted_activity_block_is_patched(tmp_path, acts, ops):
    """Deleting a parent's block with its child's reads as one delete; the
    child is gone from the fresh payload too, and that is the apply's."""
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    _delete_blocks(path, *acts)
    p = hb_pack.pack()
    read = p.read(path)
    assert [(o["op"], o["ref"]) for o in read.change_set.ops] == ops
    fresh = _without(H.fixture_doc(), set(acts))
    plan = ApplyResult.from_plan({"created": {}, "deleted": [f"activity:{a}" for a in set(acts)],
                                  "totals": {}}, dry_run=False)
    report = p.patch(path, read.change_set, plan, fresh)
    assert report.baseline_replaced and not report.problems
    _clean(path)


def test_a_deleted_activity_and_another_users_edit_are_patched(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "c.xlsx")
    _delete_blocks(path, 3, 3)
    p = hb_pack.pack()
    read = p.read(path)
    fresh = _without(H.fixture_doc(), {3})
    next(x for x in fresh["resources"] if x["id"] == 1)["quantity"] = "77.000"
    plan = ApplyResult.from_plan({"created": {}, "deleted": ["activity:3"], "totals": {}},
                                 dry_run=False)
    report = p.patch(path, read.change_set, plan, fresh)
    assert report.baseline_replaced and not report.problems
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 77
    _clean(path)
