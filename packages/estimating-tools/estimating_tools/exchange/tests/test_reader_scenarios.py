"""The spec's three scenarios, through the generic reader: a row pasted with
stale tags into another block is a create; a resource cut into another
activity is a delete plus a create, and the plan says so; an optional STEPS
block absent reads clean."""
from __future__ import annotations

from estimating_tools.exchange.reader import read_book
from estimating_tools.heavybook.columns import CR, CW
from estimating_tools.heavybook.tests import _readback as H


def _book(tmp_path):
    return H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")


def test_a_row_pasted_with_stale_tags_into_another_block_is_a_create(tmp_path):
    path = _book(tmp_path)
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    src = H.cr_row(ws, "RESOURCE", 3)                     # under activity 2
    new = H.insert_copies(ws, src, src, H.block_end(ws, 1))
    ws[f"{CR.ID}{new}"] = 3                               # the tags travel with the paste
    H.save_book(wb, path)
    cs = read_book(path)
    creates = H.ops_named(cs, "resource.create")
    assert len(creates) == 1 and creates[0]["ref"] == "new:r1"
    assert creates[0]["fields"]["activity_id"] == 1        # on the block it sits in
    assert H.ops_named(cs, "resource.delete") == []        # the original is still under 2


def test_a_resource_cut_into_another_activity_is_a_delete_and_a_create(tmp_path):
    path = _book(tmp_path)
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    src = H.cr_row(ws, "RESOURCE", 3)
    new = H.cut_rows(ws, src, src, H.block_end(ws, 1))
    H.save_book(wb, path)
    cs = read_book(path)
    assert [op["op"] for op in cs.ops] == ["resource.create", "resource.delete"]
    assert cs.ops[0]["fields"]["activity_id"] == 1 and cs.ops[1]["ref"] == 3
    # The plan says so: the create names its source activity, the delete its row.
    assert cs.summary == [f"{H.CR_TAB} row {new}: line 'Foreman' moves here from activity 2",
                          f"{H.CR_TAB}: line 'Foreman' (resource 3) deleted"]


def test_an_activity_without_a_steps_block_reads_clean(tmp_path):
    doc = H.fixture_doc()
    stepless = next(a for a in doc["activities"] if not a.get("steps"))
    path = H.build_book(doc, tmp_path / "book.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    first = H.cr_row(ws, "ACTIVITY", stepless["id"])
    assert ws[f"{CR.KIND}{first + 1}"].value == "START"   # no STEPS marker between
    cs = read_book(path)
    assert cs.ops == []


def test_an_owners_rows_of_each_block_kind_are_found_in_the_read_model(tmp_path):
    """``_check_steps_marker`` asks whether the baseline owner has rows of an
    optional block's kind; resources live flat on the workbook, steps on the
    activity, so a pack with an optional resources block must not crash."""
    from estimating_tools.exchange.reader import book as B
    from estimating_tools.exchange.reader.scan import _has_rows
    from estimating_tools.heavybook import pack as hb_pack

    opened = B.load(_book(tmp_path), pack=hb_pack.pack())
    stepped = next(a for a in opened.model.activities if a.steps)
    stepless = next(a for a in opened.model.activities if not a.steps)
    assert _has_rows(opened, stepped, "STEP") and not _has_rows(opened, stepless, "STEP")
    with_lines = next(a for a in opened.model.activities if opened.model.resources_of(a.id))
    assert _has_rows(opened, with_lines, "RESOURCE")
    crew = opened.model.crews[0]
    assert _has_rows(opened, crew, "MEMBER") == bool(crew.members)
    opened.wb.close()


def _renamed(tmp_path):
    """A built book whose stamped declaration names its child blocks
    differently (``tasks``, ``lines``, ``gang``): a pack names its blocks as
    it likes; the reader keys rows by their kind (``contract.COLLECTIONS``)."""
    import json

    path = _book(tmp_path)
    wb = H.open_book(path)
    raw = json.loads(wb["_wb"]["A1"].value)
    sheets = raw["declaration"]["sheets"]
    for key, names in (("cost_report", {"steps": "tasks", "resources": "lines"}),
                       ("crews", {"members": "gang"})):
        blocks = sheets[key]["blocks"]
        for old, new in names.items():
            blocks[new] = blocks.pop(old)
        for b in blocks.values():
            if "children" in b:
                b["children"] = [names.get(c, c) for c in b["children"]]
    wb["_wb"]["A1"] = json.dumps(raw)
    H.save_book(wb, path)
    return path


def test_renamed_child_blocks_read_clean(tmp_path):
    assert read_book(_renamed(tmp_path)).ops == []


def test_typed_rows_in_renamed_child_blocks_read_as_in_the_pack_s_own_names(tmp_path):
    def typed(path):
        wb = H.open_book(path)
        ws = wb[H.CR_TAB]
        H.type_row(ws, H.block_end(ws, 5), {
            CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "Equipment"})
        H.type_row(ws, H.cr_row(ws, "START", parent=4), {CR.DESC: "Strip", CR.QTY: 1})
        cw = wb[H.CW_TAB]
        H.type_row(cw, H.cw_row(cw, "MEMBER", 3), {CW.CODE: "Laborer", CW.COUNT: 1,
                                                   CW.OVERRIDE: 45})
        H.save_book(wb, path)
        return read_book(path).ops

    for sub in ("renamed", "plain"):
        (tmp_path / sub).mkdir()
    renamed = typed(_renamed(tmp_path / "renamed"))
    assert sorted(op["op"] for op in renamed) == [
        "crew.update_members", "resource.create", "step.add"]
    assert renamed == typed(_book(tmp_path / "plain"))
