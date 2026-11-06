from __future__ import annotations

import copy
import io
import json
import os
import stat

import pytest

from estimating_tools.estimate_spec import cli
from estimating_tools.exchange import client, registry
from estimating_tools.exchange.types import ApplyResult, BookFacts, PatchReport
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import CR
from estimating_tools.heavybook.tests import _readback as H


@pytest.fixture(autouse=True)
def packs(monkeypatch, tmp_path):
    from estimating_tools.estimate_spec import pack as fb_pack
    monkeypatch.setattr(registry, "discover",
                        lambda: registry.Discovery([fb_pack.pack(), hb_pack.pack()], []))
    monkeypatch.setenv("ESTIMATING_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    client.login("https://www.bidsheet.ai", "tok")


def _edited_book(tmp_path):
    """A built book with resource 1's quantity changed; returns (path, row)."""
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 1)
    ws[f"{CR.QTY}{row}"] = 31
    H.save_book(wb, path)
    return path, row


def _applied(doc=None):
    """The fixture payload after ``_edited_book``'s edit was applied."""
    fresh = doc or H.fixture_doc()
    for r in fresh["resources"]:
        if r["id"] == 1:
            r["quantity"] = "31.000"
            r["v"] = "0123456789abcdef"
    return fresh


def _plan(eid, ops, *, dry_run=True, request_id=None, host=None):
    return ApplyResult.from_plan({"created": {}, "deleted": [], "totals": {},
                                  "request_id": request_id or "r"}, dry_run=dry_run)


def test_packs_lists_them(capsys):
    assert cli.main(["packs"]) == 0
    out = capsys.readouterr().out
    assert "heavybook 1" in out and "fieldbook 2" in out


def test_packs_prints_discovery_problems(monkeypatch, capsys):
    monkeypatch.setattr(registry, "discover",
                        lambda: registry.Discovery([hb_pack.pack()],
                                                   ["pack x (x:pack) failed to load: boom"]))
    assert cli.main(["packs"]) == 0
    assert "failed to load: boom" in capsys.readouterr().err


def test_login_reads_the_token_from_stdin(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("secret\n"))
    assert cli.main(["login", "--host", "https://www.bidsheet.ai"]) == 0
    assert json.loads(client.token_path().read_text())["token"] == "secret"
    assert "secret" not in capsys.readouterr().out


def test_login_refuses_a_bad_host_cleanly(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("secret\n"))
    assert cli.main(["login", "--host", "http://www.bidsheet.ai"]) == 1
    assert "https" in capsys.readouterr().err


def test_fetch_writes_the_payload_to_a_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: H.fixture_doc())
    out = tmp_path / "e1.workbook.json"
    assert cli.main(["fetch", "1", "-o", str(out)]) == 0
    assert json.loads(out.read_text())["estimate"]["id"] == 1
    assert "WROTE:" in capsys.readouterr().out


def test_fetch_passes_the_item_page(monkeypatch, tmp_path):
    seen = {}

    def fake(eid, item_ids=None, host=None):
        seen.update(eid=eid, items=item_ids)
        return H.fixture_doc()

    monkeypatch.setattr(client, "fetch", fake)
    assert cli.main(["fetch", "1", "--items", "3,4", "-o", str(tmp_path / "p.json")]) == 0
    assert seen == {"eid": 1, "items": [3, 4]}


def test_fetch_with_a_bad_host_is_a_clean_error(monkeypatch, capsys):
    assert cli.main(["fetch", "1", "--host", "http://evil"]) == 1
    assert "https" in capsys.readouterr().err


def test_fetch_with_an_empty_item_list_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(client, "fetch",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    assert cli.main(["fetch", "1", "--items", ","]) == 1
    assert "no item ids given" in capsys.readouterr().err


def test_build_with_a_named_pack(tmp_path, capsys):
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()))
    out = tmp_path / "e1.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(src), "-o", str(out),
                     "--exported-at", "x"]) == 0
    assert out.exists()


@pytest.mark.parametrize("host", [[], ["--host", "https://www.bidsheet.ai/"],
                                  ["--host", "WWW.BidSheet.ai"]])
def test_build_pack_matches_the_heavybook_verb_byte_for_byte(tmp_path, host):
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()))
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(src), "-o", str(a),
                     "--exported-at", "x", *host]) == 0
    assert cli.main(["heavybook", "build", str(src), "-o", str(b), "--exported-at", "x",
                     *host]) == 0
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize("argv, err", [
    (["--host", "http://www.bidsheet.ai"], "https"),
    (["--style", "no-such-style-dir"], "style pack refused"),
])
def test_build_pack_and_the_heavybook_verb_refuse_alike(tmp_path, capsys, argv, err):
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()))
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(src), "-o", str(a), *argv]) == 1
    first = capsys.readouterr().err
    assert cli.main(["heavybook", "build", str(src), "-o", str(b), *argv]) == 1
    second = capsys.readouterr().err
    assert err in first and first == second
    assert not a.exists() and not b.exists()


@pytest.mark.parametrize("text, err", [
    (json.dumps({"estimate": "nope"}), "payload refused"),
    ("{not json", "invalid JSON in"),
])
def test_build_pack_refuses_a_bad_payload_like_the_heavybook_verb(tmp_path, capsys, text, err):
    src = tmp_path / "bad.json"
    src.write_text(text)
    out = tmp_path / "a.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(src), "-o", str(out)]) == 1
    assert err in capsys.readouterr().err
    assert not out.exists()


def test_build_pack_names_the_installed_packs_when_unknown(tmp_path, capsys):
    src = tmp_path / "e1.workbook.json"
    src.write_text("{}")
    assert cli.main(["build", "--pack", "nope", str(src)]) == 2
    assert "heavybook" in capsys.readouterr().err


def test_build_pack_fieldbook_says_not_yet(tmp_path, capsys):
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()))
    assert cli.main(["build", "--pack", "fieldbook", str(src)]) == 2
    assert "build SPEC.yaml" in capsys.readouterr().err


def test_build_with_a_yaml_still_means_fieldbook(tmp_path):
    """`est-estimate build SPEC.yaml` keeps its meaning (the authoring path)."""
    bad = tmp_path / "nope.estimate.yaml"
    bad.write_text("project: x\n")
    assert cli.main(["build", str(bad)]) != 0  # the fieldbook builder refuses, not argparse


def test_read_detects_the_pack_and_writes_the_change_set(tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    assert cli.main(["read", str(path)]) == 0
    doc = json.loads((tmp_path / "e1.changes.json").read_text())
    assert [o["op"] for o in doc["ops"]] == ["resource.update"]
    assert "heavybook" in capsys.readouterr().out


def test_read_writes_what_the_heavybook_verb_writes(tmp_path):
    path, _ = _edited_book(tmp_path)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert cli.main(["read", str(path), "-o", str(a)]) == 0
    assert cli.main(["heavybook", "read", str(path), "-o", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()


def test_read_refuses_to_overwrite_the_book(tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    before = path.read_bytes()
    assert cli.main(["read", str(path), "-o", str(path)]) == 2
    assert "workbook itself" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_read_a_missing_file_is_refused(tmp_path, capsys):
    assert cli.main(["read", str(tmp_path / "nope.xlsx")]) == 2
    assert "read refused" in capsys.readouterr().err


def test_read_a_fieldbook_book_says_not_yet(tmp_path, capsys):
    from openpyxl import Workbook
    from openpyxl.packaging.custom import StringProperty
    wb = Workbook()
    wb.custom_doc_props.append(StringProperty(name="estimate_format", value="fieldbook 2"))
    path = tmp_path / "fb.xlsx"
    wb.save(path)
    assert cli.main(["read", str(path)]) == 2
    assert "read-back" in capsys.readouterr().err


def test_apply_dry_run_prints_the_plan_and_does_not_patch(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    sent = {}

    def fake_apply(eid, ops, *, dry_run=True, request_id=None, host=None):
        sent.update(eid=eid, ops=ops, dry_run=dry_run, request_id=request_id)
        return ApplyResult.from_plan({"created": {}, "deleted": [], "warnings": ["w1"],
                                      "totals": {"before": 1, "after": 2},
                                      "request_id": request_id or "x"}, dry_run=dry_run)

    monkeypatch.setattr(client, "apply", fake_apply)
    before = path.read_bytes()
    assert cli.main(["apply", str(path)]) == 0
    assert sent["dry_run"] is True and sent["eid"] == 1 and len(sent["ops"]) == 1
    out = capsys.readouterr().out
    assert "dry run" in out and "w1" in out and "after" in out
    assert path.read_bytes() == before


def test_apply_commit_applies_fetches_and_patches(monkeypatch, tmp_path, capsys):
    path, row = _edited_book(tmp_path)
    fresh = _applied()
    calls = []

    def fake_apply(eid, ops, *, dry_run=True, request_id=None, host=None):
        calls.append((dry_run, request_id))
        return _plan(eid, ops, dry_run=dry_run, request_id=request_id)

    monkeypatch.setattr(client, "apply", fake_apply)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: fresh)
    assert cli.main(["apply", str(path), "--commit"]) == 0
    assert [c[0] for c in calls] == [False] and calls[0][1]  # a fresh request id is sent
    assert H.open_book(path)[H.CR_TAB][f"{CR.V}{row}"].value == "0123456789abcdef"
    assert "tagged" in capsys.readouterr().out


def test_apply_commit_with_a_given_request_id_resends_it(monkeypatch, tmp_path):
    path, _ = _edited_book(tmp_path)
    seen = []

    def fake_apply(eid, ops, *, dry_run=True, request_id=None, host=None):
        seen.append(request_id)
        return ApplyResult.from_plan({"created": {}, "deleted": [], "totals": {}},
                                     dry_run=dry_run)

    monkeypatch.setattr(client, "apply", fake_apply)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _applied())
    assert cli.main(["apply", str(path), "--commit", "--request-id", "retry-1"]) == 0
    assert seen == ["retry-1"]


def test_apply_with_no_changes_sends_nothing(monkeypatch, tmp_path, capsys):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "apply",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    assert cli.main(["apply", str(path)]) == 0
    assert "no changes" in capsys.readouterr().out


def test_apply_conflict_maps_op_index_to_the_row(monkeypatch, tmp_path, capsys):
    path, row = _edited_book(tmp_path)

    def refuse(*a, **k):
        raise client.ClientError("BidSheet.ai refused (409): row changed", status=409,
                                 body={"error": "row changed", "op_index": 0})

    monkeypatch.setattr(client, "apply", refuse)
    assert cli.main(["apply", str(path)]) == 3
    err = capsys.readouterr().err
    assert "row changed" in err and f"row {row}" in err


def test_apply_commit_unknown_outcome_tells_the_user_how_to_replay(monkeypatch, tmp_path,
                                                                   capsys):
    path, _ = _edited_book(tmp_path)

    def drop(eid, ops, *, dry_run=True, request_id=None, host=None):
        raise client.ClientError("no answer from BidSheet.ai (TimeoutError); the outcome is "
                                 "unknown", request_id=request_id, sent=True)

    monkeypatch.setattr(client, "apply", drop)
    assert cli.main(["apply", str(path), "--commit", "--request-id", "r-77"]) == 3
    err = capsys.readouterr().err
    assert "--commit --request-id r-77" in err and "unknown" in err


def test_apply_dry_run_transport_failure_has_no_replay_advice(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)

    def drop(eid, ops, *, dry_run=True, request_id=None, host=None):
        raise client.ClientError("could not reach BidSheet.ai: boom", request_id="r", sent=True)

    monkeypatch.setattr(client, "apply", drop)
    assert cli.main(["apply", str(path)]) == 3
    assert "--request-id" not in capsys.readouterr().err


def test_apply_with_a_bad_host_is_a_clean_error(tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    assert cli.main(["apply", str(path), "--host", "http://evil"]) == 1
    assert "https" in capsys.readouterr().err


def test_apply_commit_a_5xx_is_an_unknown_outcome(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)

    def gateway(eid, ops, *, dry_run=True, request_id=None, host=None):
        raise client.ClientError("BidSheet.ai refused (504): gateway timeout", status=504,
                                 request_id=request_id)

    monkeypatch.setattr(client, "apply", gateway)
    assert cli.main(["apply", str(path), "--commit", "--request-id", "r-504"]) == 3
    err = capsys.readouterr().err
    assert "unknown" in err and "--commit --request-id r-504" in err


def test_apply_commit_a_4xx_is_not_an_unknown_outcome(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)

    def refuse(eid, ops, *, dry_run=True, request_id=None, host=None):
        raise client.ClientError("BidSheet.ai refused (400): bad op", status=400,
                                 request_id=request_id)

    monkeypatch.setattr(client, "apply", refuse)
    assert cli.main(["apply", str(path), "--commit"]) == 3
    assert "--request-id" not in capsys.readouterr().err


def test_apply_request_id_without_commit_is_refused(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    sent = []
    monkeypatch.setattr(client, "apply", lambda *a, **k: sent.append(1))
    assert cli.main(["apply", str(path), "--request-id", "r-1"]) == 2
    assert "add --commit (nothing sent)" in capsys.readouterr().err
    assert sent == []


def test_apply_commit_an_unexpected_patch_error_still_gives_the_advice(monkeypatch, tmp_path,
                                                                      capsys):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: H.fixture_doc())

    def broken(*a, **k):
        raise TypeError("unexpected")

    monkeypatch.setattr(hb_pack.HeavyBookPack, "patch", broken)
    assert cli.main(["apply", str(path), "--commit"]) == 3
    err = capsys.readouterr().err
    assert "could not be patched: TypeError: unexpected" in err
    assert "do not run apply on this book again" in err
    assert hb_pack.pack().covered(path) == (False, None)     # a whole book: no --items
    payload = tmp_path / "e1.workbook.json"
    on = "--host https://www.bidsheet.ai"      # the book's stamp, so the rebuild goes there
    assert f"est-estimate fetch 1 {on} -o {payload}" in err
    rebuilt = tmp_path / "e1.rebuilt.xlsx"
    assert f"est-estimate build --pack heavybook {payload} {on} -o {rebuilt}" in err


def test_apply_commit_an_unexpected_fetch_error_still_gives_the_advice(monkeypatch, tmp_path,
                                                                      capsys):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)

    def broken(*a, **k):
        raise RuntimeError("socket gone")

    monkeypatch.setattr(client, "fetch", broken)
    assert cli.main(["apply", str(path), "--commit"]) == 3
    err = capsys.readouterr().err
    assert "RuntimeError: socket gone" in err and "do not run apply on this book again" in err


@pytest.mark.parametrize("verb", ["read", "apply"])
@pytest.mark.parametrize("verdict, says", [("newer", "newer version"),
                                           ("bad", "stamp is damaged")])
def test_a_newer_or_damaged_book_is_refused(monkeypatch, tmp_path, capsys, verb, verdict, says):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(hb_pack.HeavyBookPack, "detect", lambda self, facts: verdict)
    monkeypatch.setattr(client, "apply",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    assert cli.main([verb, str(path)]) == 2
    assert says in capsys.readouterr().err
    assert not (tmp_path / "e1.changes.json").exists()


def test_packs_with_none_installed(monkeypatch, capsys):
    monkeypatch.setattr(registry, "discover", lambda: registry.Discovery([], []))
    assert cli.main(["packs"]) == 0
    assert "no exchange packs installed" in capsys.readouterr().out


def test_build_pack_default_output_sits_next_to_the_json(tmp_path):
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()))
    assert cli.main(["build", "--pack", "heavybook", str(src), "--exported-at", "x"]) == 0
    assert (tmp_path / "e1.workbook.xlsx").exists()


def test_build_pack_says_format_is_ignored(tmp_path, capsys):
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()))
    assert cli.main(["build", "--pack", "heavybook", str(src), "-o", str(tmp_path / "a.xlsx"),
                     "--exported-at", "x", "--format", "somewhere"]) == 0
    assert "--format applies only to a spec build; ignored" in capsys.readouterr().err


def test_a_spec_build_says_pack_flags_are_ignored(tmp_path, capsys):
    bad = tmp_path / "nope.estimate.yaml"
    bad.write_text("project: x\n")
    cli.main(["build", str(bad), "--host", "www.bidsheet.ai"])
    assert "apply only with --pack; ignored" in capsys.readouterr().err


def test_apply_commit_fetch_failure_after_apply_is_reported(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)

    def fail(*a, **k):
        raise client.ClientError("could not reach BidSheet.ai: boom")

    monkeypatch.setattr(client, "fetch", fail)
    assert cli.main(["apply", str(path), "--commit"]) == 3
    err = capsys.readouterr().err
    assert "applied, but" in err and "do not run apply on this book again" in err


def test_apply_commit_a_locked_book_says_close_it_in_excel(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: H.fixture_doc())

    def locked(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(hb_pack.HeavyBookPack, "patch", locked)
    assert cli.main(["apply", str(path), "--commit"]) == 3
    err = capsys.readouterr().err
    assert "applied, but" in err and "close the workbook in Excel" in err
    assert "retry" not in err and "do not run apply on this book again" in err


def test_apply_commit_patch_problems_say_do_not_apply_again(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: H.fixture_doc())
    monkeypatch.setattr(hb_pack.HeavyBookPack, "patch",
                        lambda *a, **k: PatchReport(1, 1, False, ["row 9 could not be tagged"]))
    assert cli.main(["apply", str(path), "--commit"]) == 3
    captured = capsys.readouterr()
    assert "row 9 could not be tagged" in captured.out
    assert "do not run apply on this book again" in captured.err
    assert "build --pack heavybook" in captured.err


def test_apply_commit_patch_failure_says_do_not_apply_again(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: H.fixture_doc())

    def broken(*a, **k):
        raise KeyError("resource:1")

    monkeypatch.setattr(hb_pack.HeavyBookPack, "patch", broken)
    assert cli.main(["apply", str(path), "--commit"]) == 3
    err = capsys.readouterr().err
    assert "could not be patched" in err and "do not run apply on this book again" in err


@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0, reason="root ignores read-only")
def test_apply_commit_refuses_a_read_only_book_before_sending(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    sent = []
    monkeypatch.setattr(client, "apply", lambda *a, **k: sent.append(1))
    before = path.read_bytes()
    os.chmod(path, stat.S_IREAD)
    try:
        assert cli.main(["apply", str(path), "--commit"]) == 2
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    err = capsys.readouterr().err
    assert "nothing sent" in err and "read-only" in err
    assert sent == []
    assert path.read_bytes() == before


def test_heavycivil_alias_prints_a_notice(tmp_path, capsys):
    out = tmp_path / "a.xlsx"
    assert cli.main(["heavycivil", "build", str(H.FIXTURE), "-o", str(out),
                     "--exported-at", "x"]) == 0
    err = capsys.readouterr().err
    assert err.count("`heavycivil` is now `heavybook`") == 1


def test_heavybook_without_a_sub_verb_names_the_choices(capsys):
    with pytest.raises(SystemExit):
        cli.main(["heavybook"])
    err = capsys.readouterr().err
    assert "{build,read}" in err and "heavybook_command" not in err


def _page(doc, ids):
    """``doc`` narrowed to the items ``ids``, the way BidSheet.ai pages by item_ids."""
    page = copy.deepcopy(doc)
    page["items"] = [i for i in doc["items"] if i["id"] in ids]
    page["activities"] = [a for a in doc["activities"] if a["estimate_item_id"] in ids]
    acts = {a["id"] for a in page["activities"]}
    page["resources"] = [r for r in doc["resources"] if r["activity_id"] in acts]
    page["shares"] = [s for s in doc["shares"] if s["item_id"] in ids and s["activity_id"] in acts]
    page["elements"] = [e for e in doc["elements"]
                        if all(q.get("pay_item_id") in ids | {None} for q in e["quantities"])]
    page["_fetch"] = {"item_ids": sorted(ids)}          # the stamp says it is a page
    return page


def test_a_whole_book_is_fetched_and_rebuilt_without_items(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    asked = []
    monkeypatch.setattr(client, "apply", _plan)

    def fail(eid, item_ids=None, host=None):
        asked.append(item_ids)
        raise client.ClientError("could not reach BidSheet.ai: boom", sent=True)

    monkeypatch.setattr(client, "fetch", fail)
    assert cli.main(["apply", str(path), "--commit"]) == 3
    err = capsys.readouterr().err
    assert asked == [None]
    assert "--items" not in err
    payload = tmp_path / "e1.workbook.json"
    assert f"est-estimate fetch 1 --host https://www.bidsheet.ai -o {payload}" in err


def test_a_partial_book_is_patched_from_the_items_it_covers(monkeypatch, tmp_path, capsys):
    doc = H.fixture_doc()
    act = next(r["activity_id"] for r in doc["resources"] if r["id"] == 1)
    item = next(a["estimate_item_id"] for a in doc["activities"] if a["id"] == act)
    path = H.build_book(_page(doc, {item}), tmp_path / "e1.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 1)
    ws[f"{CR.QTY}{row}"] = 31
    H.save_book(wb, path)
    fresh = _page(doc, {item})
    for r in fresh["resources"]:
        if r["id"] == 1:
            r["quantity"] = "31.000"
            r["v"] = "0123456789abcdef"
    asked = []

    def fake_fetch(eid, item_ids=None, host=None):
        asked.append(item_ids)
        return fresh

    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", fake_fetch)
    assert cli.main(["apply", str(path), "--commit"]) == 0
    assert asked == [[item]]
    capsys.readouterr()
    assert cli.main(["read", str(path)]) == 0
    assert json.loads((tmp_path / "e1.changes.json").read_text())["ops"] == []


def test_a_partial_book_gets_page_rebuild_advice(monkeypatch, tmp_path, capsys):
    doc = H.fixture_doc()
    item = doc["items"][0]["id"]
    path = H.build_book(_page(doc, {item}), tmp_path / "e1.xlsx")
    assert hb_pack.pack().covered(path)[1] == [item]
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    acts = {a["id"] for a in doc["activities"] if a["estimate_item_id"] == item}
    res = next(r["id"] for r in doc["resources"] if r["activity_id"] in acts)
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', res)}"] = 999
    H.save_book(wb, path)
    monkeypatch.setattr(client, "apply", _plan)

    def fail(*a, **k):
        raise client.ClientError("could not reach BidSheet.ai: boom", sent=True)

    monkeypatch.setattr(client, "fetch", fail)
    assert cli.main(["apply", str(path), "--commit", "--host", "https://www.bidsheet.ai"]) == 3
    err = capsys.readouterr().err
    payload = tmp_path / "e1.items.workbook.json"
    assert (f"est-estimate fetch 1 --items {item} --host https://www.bidsheet.ai -o {payload}"
            in err)
    assert (f"est-estimate build --pack heavybook {payload} --host https://www.bidsheet.ai "
            f"-o {tmp_path / 'e1.rebuilt.xlsx'}") in err


def test_a_pack_that_cannot_say_what_it_covers_gets_the_whole_estimate(monkeypatch, tmp_path):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(hb_pack.HeavyBookPack, "covered",
                        lambda self, book: (_ for _ in ()).throw(RuntimeError("no")))
    asked = []
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch",
                        lambda eid, item_ids=None, host=None: asked.append(item_ids)
                        or H.fixture_doc())
    cli.main(["apply", str(path), "--commit"])
    assert asked == [None]


def test_fetch_of_a_page_defaults_to_a_page_name(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: H.fixture_doc())
    assert cli.main(["fetch", "1", "--items", "3"]) == 0
    assert (tmp_path / "e1.items.workbook.json").exists()
    assert cli.main(["fetch", "1"]) == 0
    assert (tmp_path / "e1.workbook.json").exists()


@pytest.mark.parametrize("make", ["no token", "another host"])
def test_a_commit_the_client_refused_locally_was_not_sent(monkeypatch, tmp_path, capsys, make):
    path, _ = _edited_book(tmp_path)
    opened = []
    monkeypatch.setattr(client, "_open", lambda *a, **k: opened.append(1))
    argv = ["apply", str(path), "--commit"]
    if make == "no token":
        client.token_path().unlink()
    else:
        argv += ["--host", "https://staging.example"]
    assert cli.main(argv) == 2
    err = capsys.readouterr().err
    assert "nothing sent" in err and "--request-id" not in err and "unknown" not in err
    assert opened == []


def test_fetch_without_a_token_is_refused_locally(capsys):
    client.token_path().unlink()
    assert cli.main(["fetch", "1"]) == 2
    assert "fetch refused" in capsys.readouterr().err


def test_a_not_yet_message_does_not_double_the_pack_name(tmp_path, capsys):
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()))
    assert cli.main(["build", "--pack", "fieldbook", str(src)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("fieldbook builds") and "fieldbook: fieldbook" not in err


def _book_for_host(tmp_path, host):
    """An edited book stamped for ``host`` (a bare host, as HeavyBook writes it)."""
    from estimating_tools.heavybook import build as hb_build
    from estimating_tools.heavybook import style as hb_style

    path = tmp_path / "e1.xlsx"
    book = hb_build.build(H.fixture_doc(), style=hb_style.load_style(),
                          exported_at="2026-10-20T09:00:00Z", host=host)
    hb_build.save(book, path)
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"] = 31
    H.save_book(wb, path)
    return path


@pytest.mark.parametrize("commit", [False, True])
def test_apply_goes_to_the_books_stamped_host_not_the_stored_tokens(monkeypatch, tmp_path,
                                                                     capsys, commit):
    path = _book_for_host(tmp_path, "staging.example")      # the token is for www.bidsheet.ai
    sent = []
    monkeypatch.setattr(client, "_open", lambda *a, **k: sent.append(1))
    assert cli.main(["apply", str(path)] + (["--commit"] if commit else [])) == 2
    err = capsys.readouterr().err
    assert "apply refused" in err and "(nothing sent)" in err
    assert "est-estimate login --host https://staging.example" in err
    assert sent == []


def test_apply_refuses_a_host_that_conflicts_with_the_stamp(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    sent = []
    monkeypatch.setattr(client, "apply", lambda *a, **k: sent.append(1))
    monkeypatch.setattr(client, "_open", lambda *a, **k: sent.append(1))
    assert cli.main(["apply", str(path), "--commit", "--host", "https://staging.example"]) == 2
    err = capsys.readouterr().err
    assert ("apply refused: this book was built from https://www.bidsheet.ai; --host says "
            "https://staging.example (nothing sent)") in err
    assert sent == []


@pytest.mark.parametrize("argv", [[], ["--host", "https://www.bidsheet.ai/"],
                                  ["--host", "https://WWW.bidsheet.ai"]])
def test_apply_passes_the_stamped_origin_to_apply_and_fetch(monkeypatch, tmp_path, capsys,
                                                            argv):
    path, _ = _edited_book(tmp_path)
    hosts = []

    def fake_apply(eid, ops, *, dry_run=True, request_id=None, host=None):
        hosts.append(("apply", host))
        return _plan(eid, ops, dry_run=dry_run, request_id=request_id)

    def fake_fetch(eid, item_ids=None, host=None):
        hosts.append(("fetch", host))
        return H.fixture_doc()

    monkeypatch.setattr(client, "apply", fake_apply)
    monkeypatch.setattr(client, "fetch", fake_fetch)
    monkeypatch.setattr(hb_pack.HeavyBookPack, "patch",
                        lambda *a, **k: PatchReport(1, 1, False, ["row 9 could not be tagged"]))
    assert cli.main(["apply", str(path), "--commit"] + argv) == 3
    assert hosts == [("apply", "https://www.bidsheet.ai"), ("fetch", "https://www.bidsheet.ai")]
    assert "--host https://www.bidsheet.ai" in capsys.readouterr().err


def test_an_unstamped_book_goes_to_the_given_host_else_the_stored_tokens():
    """The pre-stamp behaviour, kept for books without a ``bidsheet_host``."""
    from estimating_tools.exchange.cli import _apply_host

    facts = BookFacts(path="x")
    assert _apply_host(facts, None) is None             # client.apply uses the stored host
    assert _apply_host(facts, "https://staging.example/") == "https://staging.example"
    assert _apply_host(BookFacts(path="x", properties={"bidsheet_host": ""}), None) is None
    with pytest.raises(ValueError):
        _apply_host(facts, "http://evil")
    stamped = BookFacts(path="x", properties={"bidsheet_host": "www.bidsheet.ai"})
    assert _apply_host(stamped, None) == "https://www.bidsheet.ai"
    assert _apply_host(stamped, "https://WWW.bidsheet.ai") == "https://www.bidsheet.ai"
    with pytest.raises(LookupError, match="built from https://www.bidsheet.ai"):
        _apply_host(stamped, "https://staging.example")


def test_apply_with_a_damaged_host_stamp_is_refused(monkeypatch, tmp_path, capsys):
    path = _book_for_host(tmp_path, "https://www.bidsheet.ai/estimates")
    sent = []
    monkeypatch.setattr(client, "apply", lambda *a, **k: sent.append(1))
    assert cli.main(["apply", str(path)]) == 2
    err = capsys.readouterr().err
    assert "apply refused" in err and "host stamp" in err and "(nothing sent)" in err
    assert sent == []


def test_apply_on_a_book_marked_stale_sends_nothing(monkeypatch, tmp_path, capsys):
    from estimating_tools.exchange import writer
    from estimating_tools.exchange.reader.book import STALE_PROPERTY

    path, _ = _edited_book(tmp_path)
    writer.write(path, properties={STALE_PROPERTY: "applied r-1; patch not verified"})
    sent = []
    monkeypatch.setattr(client, "_open", lambda *a, **k: sent.append(1))
    assert cli.main(["apply", str(path), "--commit"]) == 2
    err = capsys.readouterr().err
    assert "nothing sent" in err and "could not be patched fully" in err
    assert "rebuild the book from BidSheet.ai" in err
    assert sent == []
    assert cli.main(["read", str(path)]) == 2


def test_an_apply_detection_refusal_says_nothing_sent(monkeypatch, tmp_path, capsys):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(hb_pack.HeavyBookPack, "detect", lambda self, facts: "bad")
    assert cli.main(["apply", str(path)]) == 2
    assert "(nothing sent)" in capsys.readouterr().err


def test_build_pack_prefixes_refusals_by_kind(tmp_path, capsys, monkeypatch):
    from estimating_tools.exchange.types import BuildRefused
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()), encoding="utf-8")
    for kind, prefix in (("payload", "payload refused"), ("style", "style pack refused"),
                         ("profile", "org profile refused"), ("host", "build refused"),
                         ("template", "template refused")):
        def refuse(self, payload, out, *, options, k=kind):
            raise BuildRefused(k, "boom")
        monkeypatch.setattr(hb_pack.HeavyBookPack, "build", refuse)
        assert cli.main(["build", "--pack", "heavybook", str(src)]) == 1
        assert f"{prefix}: boom" in capsys.readouterr().err


def test_build_pack_merges_pages(tmp_path):
    doc = H.fixture_doc()
    ids = [i["id"] for i in doc["items"]]
    a, b = copy.deepcopy(doc), copy.deepcopy(doc)
    a["items"] = [i for i in doc["items"] if i["id"] in ids[:2]]
    b["items"] = [i for i in doc["items"] if i["id"] in ids[2:]]
    pa, pb = tmp_path / "e1.workbook.p1.json", tmp_path / "e1.workbook.p2.json"
    pa.write_text(json.dumps(a), encoding="utf-8")
    pb.write_text(json.dumps(b), encoding="utf-8")
    out = tmp_path / "e1.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(pa), str(pb), "-o", str(out),
                     "--exported-at", "x"]) == 0
    assert out.exists()


def test_build_pack_default_output_drops_the_page_suffix(tmp_path):
    src = tmp_path / "e76.workbook.p1.json"
    src.write_text(json.dumps(H.fixture_doc()), encoding="utf-8")
    assert cli.main(["build", "--pack", "heavybook", str(src), "--exported-at", "x"]) == 0
    assert (tmp_path / "e76.workbook.xlsx").exists()


def test_a_spec_build_takes_one_config(tmp_path, capsys):
    (tmp_path / "a.yaml").write_text("x: 1", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("x: 1", encoding="utf-8")
    assert cli.main(["build", str(tmp_path / "a.yaml"), str(tmp_path / "b.yaml")]) == 1
    assert "one spec" in capsys.readouterr().err


def test_fetch_with_items_writes_the_fetch_record(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(client, "_request", lambda *a, **k: H.fixture_doc())
    assert cli.main(["fetch", "1", "--items", "3,4"]) == 0
    doc = json.loads((tmp_path / "e1.items.workbook.json").read_text(encoding="utf-8"))
    assert doc["_fetch"] == {"item_ids": [3, 4]}


def test_build_pack_refuses_a_payload_that_is_not_an_object(tmp_path, capsys):
    src = tmp_path / "e1.workbook.json"
    src.write_text("7", encoding="utf-8")
    assert cli.main(["build", "--pack", "heavybook", str(src)]) == 1
    assert "payload refused: the payload must be a JSON object" in capsys.readouterr().err


def test_build_pack_refuses_a_malformed_fetch_record(tmp_path, capsys):
    doc = H.fixture_doc()
    doc["_fetch"] = {"item_ids": ["x"]}
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "e1.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(src), "-o", str(out)]) == 1
    assert "payload refused:" in capsys.readouterr().err
    assert not out.exists()


def test_every_refusal_kind_has_a_prefix():
    from estimating_tools.exchange.cli import REFUSAL_PREFIX
    from estimating_tools.exchange.types import BUILD_REFUSAL_KINDS
    assert set(REFUSAL_PREFIX) == set(BUILD_REFUSAL_KINDS)


# -- refresh -------------------------------------------------------------------------------

def _server_changed(doc=None, qty="32.000"):
    """The fixture payload with resource 1's quantity changed in BidSheet.ai."""
    fresh = doc or H.fixture_doc()
    for r in fresh["resources"]:
        if r["id"] == 1:
            r.update(quantity=qty, v="1111111111111111")
    return fresh


def test_refresh_fetches_the_estimate_and_writes_its_changes(monkeypatch, tmp_path, capsys):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    asked = []

    def fake_fetch(eid, item_ids=None, host=None):
        asked.append((eid, item_ids, host))
        return _server_changed()

    monkeypatch.setattr(client, "fetch", fake_fetch)
    assert cli.main(["refresh", str(path)]) == 0
    assert asked == [(1, None, "https://www.bidsheet.ai")]
    ws = H.open_book(path)[H.CR_TAB]
    assert ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"].value == 32
    assert "refreshed --" in capsys.readouterr().out


def test_refresh_reports_a_collision_writes_nothing_and_exits_4(monkeypatch, tmp_path, capsys):
    path, _row = _edited_book(tmp_path)                       # resource 1 at 31 in the book
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _server_changed())
    before = path.read_bytes()
    assert cli.main(["refresh", str(path)]) == 4
    assert path.read_bytes() == before
    out = capsys.readouterr().out
    assert "BidSheet.ai 32" in out and "this book 31" in out and "nothing written" in out


def test_refresh_dry_run_writes_nothing(monkeypatch, tmp_path, capsys):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _server_changed())
    before = path.read_bytes()
    assert cli.main(["refresh", str(path), "--dry-run"]) == 0
    assert path.read_bytes() == before
    assert "dry run -- would write" in capsys.readouterr().out


def test_refresh_of_a_page_fetches_its_items(monkeypatch, tmp_path):
    doc = H.fixture_doc()
    path = H.build_book(_page(doc, {1}), tmp_path / "e1.xlsx")
    asked = []

    def fake_fetch(eid, item_ids=None, host=None):
        asked.append(item_ids)
        return _server_changed(_page(doc, {1}))

    monkeypatch.setattr(client, "fetch", fake_fetch)
    assert cli.main(["refresh", str(path)]) == 0
    assert asked == [[1]]


def test_refresh_fetch_failure_is_exit_3_and_writes_nothing(monkeypatch, tmp_path, capsys):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")

    def fail(*a, **k):
        raise client.ClientError("could not reach BidSheet.ai: boom", sent=True)

    monkeypatch.setattr(client, "fetch", fail)
    before = path.read_bytes()
    assert cli.main(["refresh", str(path)]) == 3
    assert path.read_bytes() == before
    assert "refresh failed" in capsys.readouterr().err


def test_refresh_of_a_locked_book_is_refused(monkeypatch, tmp_path, capsys):
    from estimating_tools.exchange import cli as ex_cli

    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(ex_cli, "_locked", lambda book: True)
    monkeypatch.setattr(client, "fetch", lambda *a, **k: pytest.fail("nothing is fetched"))
    assert cli.main(["refresh", str(path)]) == 2
    assert "close it" in capsys.readouterr().err


def test_refresh_of_a_book_with_a_refused_read_is_exit_2(monkeypatch, tmp_path, capsys):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    ws[f"{CR.QTY}{H.cr_row(ws, 'END', parent=2)}"] = 5         # typed on a marker row
    H.save_book(wb, path)
    monkeypatch.setattr(client, "fetch", lambda *a, **k: pytest.fail("nothing is fetched"))
    assert cli.main(["refresh", str(path)]) == 2
    assert "read refused" in capsys.readouterr().err


def test_refresh_of_a_fieldbook_book_says_not_yet(tmp_path, capsys):
    from estimating_tools.estimate_spec.tests._fieldbook import build as fb_build

    path = tmp_path / "fb.xlsx"
    fb_build().save(path)
    assert cli.main(["refresh", str(path)]) == 2
    assert "fieldbook" in capsys.readouterr().err


def test_refresh_with_another_host_is_refused(monkeypatch, tmp_path, capsys):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda *a, **k: pytest.fail("nothing is fetched"))
    before = path.read_bytes()
    assert cli.main(["refresh", str(path), "--host", "https://other.example"]) == 2
    assert "this book was built from https://www.bidsheet.ai" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_refresh_with_a_malformed_host_is_exit_1(monkeypatch, tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda *a, **k: pytest.fail("nothing is fetched"))
    assert cli.main(["refresh", str(path), "--host", "http://evil"]) == 1


def test_refresh_a_fetch_that_does_not_merge_is_exit_3(monkeypatch, tmp_path, capsys):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")

    def bad(*a, **k):
        raise ValueError("the estimate changed between pages")

    monkeypatch.setattr(client, "fetch", bad)
    before = path.read_bytes()
    assert cli.main(["refresh", str(path)]) == 3
    assert "refresh failed" in capsys.readouterr().err
    assert path.read_bytes() == before


# -- the opt-in calculating pass after a patch (#370) -----------------------------------
# The patch already re-caches values with the built-in evaluator (#445); an
# engine pass runs only on ``--recalc excel`` (or auto/libreoffice).

@pytest.fixture
def recalc_spy(monkeypatch):
    from estimating_tools import xlsx_recalc
    calls = []

    def fake(path, *, engine="auto", **kw):
        calls.append({"path": str(path), "engine": engine, **kw})
        return xlsx_recalc.RecalcResult("excel-com", "Excel (pywin32)")

    monkeypatch.setattr(xlsx_recalc, "recalculate", fake)
    return calls


def test_apply_commit_runs_no_engine_by_default(monkeypatch, tmp_path, capsys, recalc_spy):
    """The built-in evaluator re-cached the patched book: no engine, no line."""
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _applied())
    assert cli.main(["apply", str(path), "--commit"]) == 0
    assert recalc_spy == []
    out = capsys.readouterr().out
    assert "patched" in out and "RECALC" not in out


@pytest.mark.parametrize("choice", ["auto", "excel", "libreoffice"])
def test_apply_commit_recalcs_the_patched_book_when_asked(monkeypatch, tmp_path, capsys,
                                                          recalc_spy, choice):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _applied())
    assert cli.main(["apply", str(path), "--commit", "--recalc", choice]) == 0
    assert recalc_spy == [{"path": str(path), "engine": choice}]
    out = capsys.readouterr().out
    assert out.index("patched") < out.index("RECALC: excel-com")


def test_apply_commit_recalc_off_runs_nothing(monkeypatch, tmp_path, capsys, recalc_spy):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _applied())
    assert cli.main(["apply", str(path), "--commit", "--recalc", "off"]) == 0
    assert recalc_spy == [] and "RECALC" not in capsys.readouterr().out


def test_apply_dry_run_does_not_recalc(monkeypatch, tmp_path, recalc_spy):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    assert cli.main(["apply", str(path), "--recalc", "excel"]) == 0
    assert recalc_spy == []


def test_a_patch_that_wrote_only_the_stamp_does_not_recalc(monkeypatch, tmp_path, recalc_spy):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _applied())
    monkeypatch.setattr(hb_pack.HeavyBookPack, "patch", lambda *a, **k: PatchReport(
        cells_written=2, rows_tagged=0, baseline_replaced=True, recalc=False))
    assert cli.main(["apply", str(path), "--commit", "--recalc", "excel"]) == 0
    assert recalc_spy == []


def test_the_heavybook_patch_reports_that_it_wrote_inputs(monkeypatch, tmp_path):
    path, _ = _edited_book(tmp_path)
    monkeypatch.setattr(client, "apply", _plan)
    seen = []
    real = hb_pack.HeavyBookPack.patch

    def spy(self, *a, **k):
        report = real(self, *a, **k)
        seen.append(report)
        return report

    monkeypatch.setattr(hb_pack.HeavyBookPack, "patch", spy)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _applied())
    assert cli.main(["apply", str(path), "--commit"]) == 0
    assert seen and seen[0].recalc is True


def test_a_refresh_runs_no_engine_by_default(monkeypatch, tmp_path, capsys, recalc_spy):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _server_changed())
    assert cli.main(["refresh", str(path)]) == 0
    assert recalc_spy == []
    out = capsys.readouterr().out
    assert "refreshed --" in out and "RECALC" not in out


@pytest.mark.parametrize("choice", ["auto", "excel"])
def test_a_refresh_that_wrote_the_book_recalcs_it_when_asked(monkeypatch, tmp_path, capsys,
                                                             recalc_spy, choice):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _server_changed())
    assert cli.main(["refresh", str(path), "--recalc", choice]) == 0
    assert recalc_spy == [{"path": str(path), "engine": choice}]
    out = capsys.readouterr().out
    assert out.index("refreshed --") < out.index("RECALC: excel-com")


def test_a_refresh_with_recalc_off_runs_nothing(monkeypatch, tmp_path, recalc_spy):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _server_changed())
    assert cli.main(["refresh", str(path), "--recalc", "off"]) == 0
    assert recalc_spy == []


def test_a_dry_run_refresh_does_not_recalc(monkeypatch, tmp_path, recalc_spy):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _server_changed())
    assert cli.main(["refresh", str(path), "--dry-run", "--recalc", "excel"]) == 0
    assert recalc_spy == []


def test_a_reported_refresh_does_not_recalc(monkeypatch, tmp_path, recalc_spy):
    path, _row = _edited_book(tmp_path)
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _server_changed())
    assert cli.main(["refresh", str(path), "--recalc", "excel"]) == 4
    assert recalc_spy == []


def test_a_current_book_is_not_recalced(monkeypatch, tmp_path, recalc_spy):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: H.fixture_doc())
    assert cli.main(["refresh", str(path), "--recalc", "excel"]) == 0
    assert recalc_spy == []


def test_a_refresh_with_recalc_switched_off_everywhere_writes_no_pass(monkeypatch, tmp_path,
                                                                      capsys):
    from estimating_tools import xlsx_recalc

    monkeypatch.setenv(xlsx_recalc.ENV_VAR, "off")
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    monkeypatch.setattr(client, "fetch", lambda eid, item_ids=None, host=None: _server_changed())
    assert cli.main(["refresh", str(path), "--recalc", "excel"]) == 0
    out = capsys.readouterr().out
    assert "RECALC" in out and "off" in out.split("RECALC", 1)[1].splitlines()[0]
