import pytest
import yaml

from estimating_tools.quotes.intake.inventory import (
    Inventory, inbox_dir_for, state_dir_for)
from estimating_tools.quotes.intake.scan import MSG_REASON, scan_inbox
from estimating_tools.quotes.tests._intake import (
    make_eml, make_pdf, make_png, make_xlsx, spec_on_disk)


def _setup(tmp_path):
    spec_path = spec_on_disk(tmp_path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    state = state_dir_for(spec_path, spec)
    return inbox_dir_for(spec_path, spec), state, Inventory.load(state)


def test_scan_records_new_files_and_names_unsupported_suffixes_once(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    pdf = make_pdf(inbox / "Rebar quote.pdf", ["hello"])
    (inbox / "sub").mkdir()
    make_xlsx(inbox / "sub" / "Haul.xlsx", {"S": [[1, 2]]})
    (inbox / "notes.zip").write_bytes(b"zip")
    (inbox / "old.doc").write_bytes(b"doc")
    report = scan_inbox(inv, inbox, state)
    assert report.new == 2
    assert report.unsupported == {".zip": 1, ".doc": 1}
    assert report.summary() == "2 new, 0 known, 2 unsupported"
    doc = inv.by_path(str(pdf))
    assert (doc.kind, doc.status, doc.route) == ("pdf", "new", None)
    assert doc.paths == [str(pdf)] and doc.size == pdf.stat().st_size


def test_scan_is_idempotent_and_collapses_byte_identical_duplicates(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    a = make_pdf(inbox / "Proposal.pdf", ["same"])
    b = inbox / "Proposal (1).pdf"
    b.write_bytes(a.read_bytes())
    assert scan_inbox(inv, inbox, state).new == 1
    docs = list(inv)
    assert len(docs) == 1 and len(docs[0].paths) == 2
    again = scan_inbox(inv, inbox, state)
    assert (again.new, again.known) == (0, 2)


def test_scan_skips_intake_and_dot_folders(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    for folder in ("_intake", ".hidden"):
        (inbox / folder).mkdir()
        make_pdf(inbox / folder / "x.pdf", ["x"])
    assert scan_inbox(inv, inbox, state).new == 0
    assert list(inv) == []


def test_a_resaved_file_is_a_new_record_that_supersedes_the_old(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    path = make_pdf(inbox / "q.pdf", ["one"])
    scan_inbox(inv, inbox, state)
    (old,) = list(inv)
    make_pdf(path, ["two"])
    scan_inbox(inv, inbox, state)
    (new,) = list(inv)
    assert new.sha256 != old.sha256
    assert old.superseded_by == new.sha256 and old.paths == [str(path)]
    assert new.status == "new"


def test_an_msg_file_is_held_with_the_reason(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    (inbox / "mail.msg").write_bytes(b"\xd0\xcf\x11\xe0")
    scan_inbox(inv, inbox, state)
    (doc,) = list(inv)
    assert (doc.kind, doc.route, doc.status, doc.reason) == (
        "msg", "unsupported", "held", MSG_REASON)


def test_an_eml_is_unpacked_into_its_body_and_attachments(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    pdf = make_pdf(tmp_path / "Quote.pdf", ["q"])
    png = make_png(tmp_path / "logo.png")
    eml = make_eml(inbox / "m.eml", subject="Quote", body_text=None,
                   body_html="<p>Price <b>$1.42</b>/LB</p><style>x</style>",
                   attachments=[pdf, png])
    report = scan_inbox(inv, inbox, state)
    (mail,) = [d for d in inv if d.kind == "eml"]
    assert report.new == 4
    assert mail.status == "not_quote"
    assert mail.reason == "email container: 3 document(s) unpacked"
    folder = state / "docs" / mail.sha256
    assert (folder / "body.txt").read_text(encoding="utf-8").endswith("\n\nPrice $1.42/LB")
    kids = {d.kind: d for d in inv if d.parent == mail.sha256}
    assert set(kids) == {"txt", "pdf", "png"}
    assert kids["txt"].status == "new"
    for d in kids.values():
        assert d.paths[0].startswith(str(folder))
    before = sorted(p.name for p in (state / "docs").rglob("*"))
    again = scan_inbox(inv, inbox, state)
    assert again.new == 0
    assert sorted(p.name for p in (state / "docs").rglob("*")) == before
    assert eml.exists()


def test_a_missing_inbox_is_reported_not_raised(tmp_path):
    _, state, inv = _setup(tmp_path)
    gone = tmp_path / "nope"
    report = scan_inbox(inv, gone, state)
    assert report.lines == [f"inbox {gone} does not exist"] and report.new == 0
    assert report.missing_inbox and not report.changed and not inv.dirty


def test_a_no_op_scan_leaves_the_inventory_clean_and_a_new_file_dirties_it(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_pdf(inbox / "a.pdf", ["one"])
    first = scan_inbox(inv, inbox, state)
    assert first.changed and inv.dirty and not first.missing_inbox
    inv.save()
    assert not inv.dirty
    again = scan_inbox(inv, inbox, state)
    assert not again.changed and not inv.dirty
    make_pdf(inbox / "b.pdf", ["two"])
    third = scan_inbox(inv, inbox, state)
    assert third.new == 1 and third.changed and inv.dirty


def test_inventory_round_trips_and_find_needs_a_unique_prefix(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_pdf(inbox / "a.pdf", ["a"])
    make_pdf(inbox / "b.pdf", ["b"])
    scan_inbox(inv, inbox, state)
    inv.save()
    loaded = Inventory.load(state)
    assert loaded.all() == inv.all()
    doc = inv.all()[0]
    assert loaded.find(doc.sha256[:8]) == doc
    with pytest.raises(ValueError, match="no document abc"):
        loaded.find("abc")
    shared = Inventory(state / "inventory.json")
    from dataclasses import replace
    shared.add(doc)
    shared.add(replace(doc, sha256=doc.sha256[:8] + "0" * 56))
    with pytest.raises(ValueError, match="ambiguous"):
        shared.find(doc.sha256[:8])


def test_hostile_attachment_names_stay_under_the_eml_folder(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    pdf = make_pdf(tmp_path / "x.pdf", ["x"])
    eml = inbox / "m.eml"
    import email.message
    msg = email.message.EmailMessage()
    msg["Subject"] = "s"
    msg.set_content("hi")
    for i, name in enumerate(["../../evil.pdf", "..", "a\\b.pdf", "z" * 300 + ".pdf"]):
        msg.add_attachment(pdf.read_bytes() + bytes([i]), maintype="application",
                           subtype="pdf", filename=name)
    eml.write_bytes(msg.as_bytes())
    scan_inbox(inv, inbox, state)
    (mail,) = [d for d in inv if d.kind == "eml"]
    folder = state / "docs" / mail.sha256
    files = [p for p in state.rglob("*") if p.is_file() and p.name != "inventory.json"]
    assert len(files) == 5
    assert all(p.parent == folder for p in files)
    assert all(len(p.name) <= 125 for p in files)


def test_a_bad_eml_is_recorded_as_error_and_the_scan_continues(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_pdf(inbox / "good.pdf", ["g"])
    (inbox / "bad.eml").write_bytes(
        b"Subject: s\nContent-Type: text/plain; charset=x-nonexistent\n"
        b"Content-Transfer-Encoding: 8bit\n\nbody\n")
    scan_inbox(inv, inbox, state)
    docs = {d.kind: d for d in inv}
    assert docs["pdf"].status == "new"
    assert docs["eml"].status == "error" and docs["eml"].reason


def test_a_revert_makes_the_old_record_live_again(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    path = make_pdf(inbox / "q.pdf", ["A"])
    scan_inbox(inv, inbox, state)
    (a,) = list(inv)
    make_pdf(path, ["B"])
    scan_inbox(inv, inbox, state)
    make_pdf(path, ["A"])
    scan_inbox(inv, inbox, state)
    (live,) = list(inv)
    assert live is a and a.superseded_by is None
    (b,) = [d for d in inv.all() if d is not a]
    assert b.superseded_by == a.sha256


def test_resaving_one_of_two_identical_copies_keeps_the_record_live(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    p1 = make_pdf(inbox / "p1.pdf", ["same"])
    (inbox / "p2.pdf").write_bytes(p1.read_bytes())
    scan_inbox(inv, inbox, state)
    (orig,) = list(inv)
    make_pdf(p1, ["changed"])
    scan_inbox(inv, inbox, state)
    live = list(inv)
    assert len(live) == 2 and orig in live and orig.superseded_by is None


def test_an_eml_body_starts_with_its_marked_headers(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    eml = make_eml(inbox / "m.eml", subject="Hauling quote", body_text="Haul 16.50 / CY\n",
                   body_html=None, attachments=[])
    import email
    msg = email.message_from_bytes(eml.read_bytes())
    msg["Date"] = "Tue, 20 Oct 2026 09:15:00 -0700"
    eml.write_bytes(msg.as_bytes())
    scan_inbox(inv, inbox, state)
    (mail,) = [d for d in inv if d.kind == "eml"]
    body = (state / "docs" / mail.sha256 / "body.txt").read_text(encoding="utf-8")
    assert body == ("[email headers -- not part of the quote body]\n"
                    "From: sales@vendor.example\n"
                    "Date: Tue, 20 Oct 2026 09:15:00 -0700\n"
                    "Subject: Hauling quote\n"
                    "\n"
                    "Haul 16.50 / CY\n")
