"""`est-estimate packages push | pull | push --apply`, and the round trip push -> apply -> pull."""
from __future__ import annotations

import copy
import json
from itertools import count

import pytest
import yaml

from estimating_tools.estimate_spec import cli
from estimating_tools.estimate_spec.bm_sync.apply import resolve_path
from estimating_tools.estimate_spec.bm_sync.sidecar import Sidecar
from estimating_tools.estimate_spec.tests._bm_fixture import acme_rebar, export_builder, spec_two_packages
from estimating_tools.quotes.files import load_quote_file, write_quote_file

ACME_FILE = "acme-rebar--reinforcing-steel.json"
REBAR = "Reinforcing steel"
WP_IDS = {REBAR: 273, "Ready-mix concrete": 274}     # BidSheet.ai work package ids
ITEM_IDS = {"61": 7001, "62": 7002}                  # work package item ids
PKG_ITEMS = {REBAR: ["61"], "Ready-mix concrete": ["62"]}


@pytest.fixture(autouse=True)
def _no_ambient_profile(monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)


def run(*argv) -> int:
    return cli.main(["packages", *map(str, argv)])


def write_spec(tmp_path, **choice):
    """The two-package spec with `choice` (selected/pinned/picks) on the rebar package."""
    spec = spec_two_packages()
    spec["work_packages"][0].update(choice)
    path = tmp_path / "b.estimate.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def initial_export(*names) -> dict:
    """The export before any push: the named packages, no quotes, Acme in the directory."""
    b = export_builder().organization(4722, "ACME REBAR")
    for name in names or WP_IDS:
        b.package(name, WP_IDS[name], {n: ITEM_IDS[n] for n in PKG_ITEMS[name]})
    return b.build()


def setup(tmp_path, export=None, quotes=(ACME_FILE,), **choice):
    spec_path = write_spec(tmp_path, **choice)
    qdir = tmp_path / "quotes"
    qdir.mkdir()
    if ACME_FILE in quotes:
        write_quote_file(qdir / ACME_FILE, acme_rebar())
    bm = tmp_path / "export.json"
    bm.write_text(json.dumps(export if export is not None else initial_export()))
    return spec_path, qdir, bm


# ---------- simulating BidSheet.ai ----------

def simulate(plan: dict) -> dict:
    """A result per plan op, as BidSheet.ai would answer it: enough for the op's
    sidecar paths and for every `$ref` a later op takes from it."""
    line_ids, quote_ids = count(901), count(55)
    results = {}
    for op in plan["ops"]:
        kind, args = op["kind"], op["args"]
        if kind == "ensure_package":
            wpid = WP_IDS[op["package"]]
            result = {"id": wpid, "estimate_package_id": wpid + 1000}
        elif kind == "assign_items":
            result = {"items": [{"item_number": n, "work_package_item_id": ITEM_IDS[n]}
                                for n in args["item_numbers"]]}
        elif kind == "create_vendor":
            result = {"id": 4722}
        elif kind == "create_quote":
            vendor = args["vendor_id"] if isinstance(args["vendor_id"], int) else 4722
            result = {"id": next(quote_ids), "revision": 1, "vendor_id": vendor}
        elif kind == "create_line":
            result = {"id": next(line_ids)}
        elif kind == "create_revision":
            items = [p.rsplit(".lines.", 1)[1] for p in op["sidecar"] if ".lines." in p]
            result = {"id": next(quote_ids), "revision": 2,
                      "line_items": [{"id": next(line_ids), "item_number": n} for n in items]}
        else:   # carry, allocate, remove_allocation, acknowledge, recalc, remove_plug
            result = {}
        results[op["id"]] = result
    return {"results": results}


class Replay:
    """BidSheet.ai after the push: the pre-push export with the plan's ops replayed in
    order, every `$ref` resolved through the simulated results. Quote ids, revisions and
    line ids come from the results; line prices from the line ops' args; the carry mode,
    carried quote and allocations from the carry/allocate/remove_allocation ops."""

    def __init__(self, export: dict, plan: dict, results: dict):
        self.export = copy.deepcopy(export)
        self.results = results["results"]
        self.allocation_ids = count(800)
        for op in plan["ops"]:
            getattr(self, op["kind"], self.other)(op, self.results[op["id"]])

    def ref(self, value):
        if isinstance(value, dict) and "$ref" in value:
            return resolve_path(self.results[value["$ref"]], value.get("path", "$"))
        return value

    def pkg(self, name) -> dict:
        return next(p for p in self.export["packages"] if p["name"] == name)

    def quote(self, quote_id) -> tuple[dict, dict]:
        """The package and the current quote with that id."""
        for p in self.export["packages"]:
            for q in p["quotes"]:
                if q["quote_id"] == quote_id and q["is_current"]:
                    return p, q
        raise KeyError(quote_id)

    def line(self, line_id) -> dict:
        for p in self.export["packages"]:
            for q in p["quotes"]:
                for ln in q["line_items"]:
                    if ln["line_id"] == line_id:
                        return ln
        raise KeyError(line_id)

    @staticmethod
    def priced(args) -> dict:
        return {k: args[k] for k in ("unit_price", "quantity", "amount", "is_included",
                                     "is_alternate", "exclusion_notes") if k in args}

    # ---- the ops ----

    def ensure_package(self, op, r):
        self.export["packages"].append({
            "name": op["args"]["name"], "work_package_id": r["id"],
            "estimate_package_id": r["estimate_package_id"], "items": [], "carry_mode": "automatic",
            "selected_quote": None, "self_perform": False, "new_quotes_since_carry": False,
            "quotes": [], "components": {}})

    def assign_items(self, op, r):
        self.pkg(op["package"])["items"] += [
            {"item_number": it["item_number"], "work_package_item_id": it["work_package_item_id"],
             "project_bid_item_id": None, "estimate_item_id": None, "schedule_name": "Base"}
            for it in r["items"]]

    def create_quote(self, op, r):
        a = op["args"]
        assert self.ref(a["work_package_id"]) == self.pkg(op["package"])["work_package_id"]
        self.pkg(op["package"])["quotes"].append({
            "quote_id": r["id"], "vendor_name": a["vendor_name"], "vendor_id": self.ref(a["vendor_id"]),
            "revision": r["revision"], "status": "received", "amount": a["amount"],
            "notes": a.get("notes"), "separate_acceptance_permitted": None, "acceptance_notes": None,
            "is_current": True, "line_items": [], "allocations": []})

    def create_line(self, op, r):
        _p, q = self.quote(self.ref(op["args"]["quote_id"]))
        item = next(k.rsplit(".lines.", 1)[1] for k in op["sidecar"])
        q["line_items"].append({"item_number": item, "line_id": r["id"], "is_included": True,
                                "is_alternate": False, **self.priced(op["args"])})

    def create_revision(self, op, r):
        p, old = self.quote(op["args"]["quote_id"])
        old["is_current"] = False
        ids = {li["item_number"]: li["id"] for li in r["line_items"]}
        p["quotes"].append({**old, "quote_id": r["id"], "revision": r["revision"], "is_current": True,
                            "amount": op["args"]["amount"], "notes": op["args"]["notes"], "allocations": [],
                            "line_items": [{**ln, "line_id": ids.get(ln["item_number"])}
                                           for ln in old["line_items"]]})

    def update_line(self, op, r):
        self.line(self.ref(op["args"]["line_item_id"])).update(self.priced(op["args"]))

    def delete_line(self, op, r):
        line_id = self.ref(op["args"]["line_item_id"])
        for p in self.export["packages"]:
            for q in p["quotes"]:
                q["line_items"] = [ln for ln in q["line_items"] if ln["line_id"] != line_id]

    def carry(self, op, r):
        a = op["args"]
        p = self.pkg(op["package"])
        assert self.ref(a["work_package_id"]) == p["work_package_id"]
        quote_id = self.ref(a["quote_id"])
        for q in p["quotes"]:
            q["allocations"] = []
        p["carry_mode"] = "pinned" if a["pin"] else "automatic"
        if a["pin"] and quote_id:
            _p, q = self.quote(quote_id)
            p["selected_quote"] = {"id": quote_id, "vendor_name": q["vendor_name"]}
        else:
            p["selected_quote"] = None

    def allocate(self, op, r):
        line_id = self.ref(op["args"]["quote_line_item_id"])
        p = self.pkg(op["package"])
        q = next(q for q in p["quotes"] if q["is_current"]
                 and any(ln["line_id"] == line_id for ln in q["line_items"]))
        p["carry_mode"], p["selected_quote"] = "pinned", None
        q["allocations"].append({"allocation_id": next(self.allocation_ids), "quote_line_item_id": line_id,
                                 "allocation_type": op["args"]["allocation_type"], "accept_alternate": False})

    def remove_allocation(self, op, r):
        for q in self.pkg(op["package"])["quotes"]:
            q["allocations"] = [a for a in q["allocations"]
                                if a["allocation_id"] != op["args"]["allocation_id"]]

    def other(self, op, r):   # create_vendor, acknowledge, recalc, remove_plug: no export change
        pass


def push_and_apply(tmp_path, spec_path, bm, capsys) -> tuple[Sidecar, dict]:
    """Push, simulate BidSheet.ai's results, apply them; the sidecar and the export
    BidSheet.ai would give after the push."""
    plan_path = tmp_path / "push.plan.json"
    assert run("push", spec_path, "--bm", bm, "-o", plan_path) == 0
    plan = json.loads(plan_path.read_text())
    results = simulate(plan)
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results))
    assert run("push", "--apply", results_path, "--plan", plan_path, spec_path) == 0
    capsys.readouterr()
    after = Replay(json.loads(bm.read_text()), plan, results).export
    return Sidecar.load(tmp_path / "quotes" / "_bm" / "bm-sync.json"), after


# ---------- push ----------

def test_push_writes_plan_and_prints_render(tmp_path, capsys):
    spec_path, qdir, bm = setup(tmp_path, selected="Acme Rebar")
    assert run("push", spec_path, "--bm", bm) == 0
    out = capsys.readouterr().out
    assert out.startswith("Push plan:") and "create_quote" in out
    plan_path = qdir / "_bm" / "push.plan.json"
    plan = json.loads(plan_path.read_text())
    assert plan["direction"] == "push" and plan["spec"] == spec_path.name
    assert str(plan_path) in out


def test_push_refuses_old_export(tmp_path, capsys):
    old = initial_export()
    del old["packages"][0]["carry_mode"]
    spec_path, _qdir, bm = setup(tmp_path, export=old)
    assert run("push", spec_path, "--bm", bm) == 2
    assert "carry_mode" in capsys.readouterr().err


def test_push_unreadable_quote_file_names_it(tmp_path, capsys):
    spec_path, qdir, bm = setup(tmp_path)
    (qdir / "broken.json").write_text("{not json")
    assert run("push", spec_path, "--bm", bm) == 2
    assert "broken.json" in capsys.readouterr().err


def test_push_strict_fails_on_a_refusal(tmp_path, capsys):
    spec_path, _qdir, bm = setup(tmp_path, selected="Zed Rebar")
    assert run("push", spec_path, "--bm", bm) == 0
    assert "refused Reinforcing steel" in capsys.readouterr().out
    assert run("push", spec_path, "--bm", bm, "--strict") == 1


def test_push_needs_bm_without_apply(tmp_path, capsys):
    spec_path, _qdir, _bm = setup(tmp_path)
    assert run("push", spec_path) == 2
    assert "--bm" in capsys.readouterr().err


# ---------- apply ----------

def test_apply_updates_sidecar(tmp_path, capsys):
    spec_path, qdir, bm = setup(tmp_path, selected="Acme Rebar")
    assert run("push", spec_path, "--bm", bm) == 0
    plan_path = qdir / "_bm" / "push.plan.json"
    plan = json.loads(plan_path.read_text())
    results = tmp_path / "results.json"
    results.write_text(json.dumps(simulate(plan)))
    capsys.readouterr()
    assert run("push", "--apply", results, "--plan", plan_path, spec_path) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"applied {len(plan['ops'])}"
    sc = Sidecar.load(qdir / "_bm" / "bm-sync.json")
    sync = sc.packages[REBAR].quotes[ACME_FILE]
    assert (sync.quote_id, sync.revision, sync.lines) == (55, 1, {"61": 901})
    assert sc.packages[REBAR].bm_choice == {"carry_mode": "pinned", "selected_quote_id": 55,
                                            "hand_items": []}


def test_apply_reports_errors_and_skips(tmp_path, capsys):
    spec_path, qdir, bm = setup(tmp_path, selected="Acme Rebar")
    assert run("push", spec_path, "--bm", bm) == 0
    plan_path = qdir / "_bm" / "push.plan.json"
    plan = json.loads(plan_path.read_text())
    cq = next(o["id"] for o in plan["ops"] if o["kind"] == "create_quote")
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"results": {cq: {"error": "vendor is archived"}}}))
    capsys.readouterr()
    assert run("push", "--apply", results, "--plan", plan_path, spec_path) == 1
    out = capsys.readouterr().out
    assert f"error {cq}: vendor is archived" in out and "skipped " in out


def test_apply_refuses_a_plan_for_another_spec(tmp_path, capsys):
    spec_path, qdir, bm = setup(tmp_path, selected="Acme Rebar")
    assert run("push", spec_path, "--bm", bm) == 0
    plan_path = qdir / "_bm" / "push.plan.json"
    plan = json.loads(plan_path.read_text())
    plan["spec"] = "other.estimate.yaml"
    plan_path.write_text(json.dumps(plan))
    results = tmp_path / "results.json"
    results.write_text(json.dumps(simulate(plan)))
    capsys.readouterr()
    assert run("push", "--apply", results, "--plan", plan_path, spec_path) == 2
    assert "plan is for other.estimate.yaml, not b.estimate.yaml" in capsys.readouterr().err
    assert not (qdir / "_bm" / "bm-sync.json").exists()

# ---------- the round trip ----------

@pytest.mark.parametrize("choice", [
    {"selected": "Acme Rebar"},
    {"selected": "ARR", "pinned": True},
    {"selected": "ARR", "picks": {"61": "Acme Rebar"}},
], ids=["pinned-vendor", "pinned-arr", "picks"])
def test_round_trip_push_apply_pull_is_empty(tmp_path, capsys, choice):
    # the export lacks the ready-mix package: the push creates it too
    spec_path, _qdir, bm = setup(tmp_path, export=initial_export(REBAR), **choice)
    sidecar, export = push_and_apply(tmp_path, spec_path, bm, capsys)
    assert sidecar.packages["Ready-mix concrete"].work_package_id == 274
    assert sidecar.packages[REBAR].quotes[ACME_FILE].quote_id == 55
    rebar = next(p for p in export["packages"] if p["name"] == REBAR)
    assert rebar["carry_mode"] == "pinned"     # every case pins the rebar package
    (line,) = rebar["quotes"][0]["line_items"]
    assert (line["unit_price"], line["quantity"]) == (1.65, 1000)

    after = tmp_path / "after.json"
    after.write_text(json.dumps(export))
    pull_plan = tmp_path / "pull.plan.json"
    assert run("pull", spec_path, "--bm", after, "-o", pull_plan) == 0
    out = capsys.readouterr().out
    assert out.startswith("Pull plan: 0 op(s)"), out
    plan = json.loads(pull_plan.read_text())
    assert plan["ops"] == [] and not [e for e in plan["entries"] if e["kind"] in ("conflict", "refused")]
    assert plan["sidecar_updates"] == [] and plan["spec_changes"] == {}

    # and the push from that state is a no-op too
    assert run("push", spec_path, "--bm", after) == 0
    assert capsys.readouterr().out.startswith("Push plan: 0 op(s)")


# ---------- pull ----------

def test_pull_write_touches_files_spec_sidecar(tmp_path, capsys):
    ex = (export_builder().package(REBAR, 273, {"61": 7001}, carry_mode="pinned",
                                   selected_quote={"id": 55, "vendor_name": "Acme Rebar"})
          .package("Ready-mix concrete", 274, {"62": 7002})
          .quote(REBAR, 55, "Acme Rebar", 4722, amount=1650.0,
                 lines=[{"item_number": "61", "line_id": 901, "unit_price": 1.65, "quantity": 1000}])
          .build())
    spec_path, qdir, bm = setup(tmp_path, export=ex, quotes=())
    assert run("pull", spec_path, "--bm", bm) == 0
    assert "dry run" in capsys.readouterr().out and not (qdir / ACME_FILE).exists()

    assert run("pull", spec_path, "--bm", bm, "--write") == 0
    assert load_quote_file(qdir / ACME_FILE).vendor_id == 4722
    pkg = yaml.safe_load(spec_path.read_text())["work_packages"][0]
    assert pkg["selected"] == "Acme Rebar" and pkg["pinned"] is True
    assert len(list(tmp_path.glob("b.estimate.yaml.bak-*"))) == 1
    sc = Sidecar.load(qdir / "_bm" / "bm-sync.json")
    assert sc.packages[REBAR].quotes[ACME_FILE].revision == 1

    capsys.readouterr()
    assert run("pull", spec_path, "--bm", bm, "--write") == 0
    out = capsys.readouterr().out
    assert out.startswith("Pull plan: 0 op(s)") and "nothing to write" in out


def _assemblies_spec(tmp_path):
    path = tmp_path / "b.estimate.yaml"
    path.write_text(yaml.safe_dump(spec_two_packages(), sort_keys=False), encoding="utf-8")
    return path


def test_cli_assemblies_writes_payloads_and_report(tmp_path, capsys):
    spec_path = _assemblies_spec(tmp_path)
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps({"assemblies": {"61": {"T1:61:01:crew": 3616}}}))
    out = tmp_path / "out"
    rc = cli.main(["assemblies", str(spec_path), "-o", str(out), "--bid", "T1", "--existing", str(ids)])
    assert rc == 0
    assert len(json.loads((out / "61.json").read_text())) == 3
    report = (out / "assemblies-report.md").read_text()
    assert report.startswith("# Assemblies T1") and "delete_assembly 3616" in report
    assert "# Assemblies T1" in capsys.readouterr().out


def test_cli_assemblies_compare_exit_code(tmp_path, capsys):
    spec_path = _assemblies_spec(tmp_path)
    out = tmp_path / "out"
    assert cli.main(["assemblies", str(spec_path), "-o", str(out), "--bid", "T1"]) == 0
    assert cli.main(["assemblies", str(spec_path), "-o", str(tmp_path / "again"), "--bid", "T1",
                     "--compare", str(out)]) == 0
    old = json.loads((out / "61.json").read_text())
    old[1]["components"][0]["unit_cost"] = 1.9
    (out / "61.json").write_text(json.dumps(old))
    capsys.readouterr()
    rc = cli.main(["assemblies", str(spec_path), "-o", str(tmp_path / "again"), "--bid", "T1",
                   "--compare", str(out)])
    assert rc == 1
    assert "1 with differences" in capsys.readouterr().out


def test_cli_assemblies_reads_the_sidecar_and_reports_bad_inputs(tmp_path, capsys):
    spec_path = _assemblies_spec(tmp_path)
    sc = Sidecar()
    sc.package(REBAR).plugs_removed = {"61": ["3617:9001"]}
    (tmp_path / "quotes" / "_bm").mkdir(parents=True)
    sc.save(tmp_path / "quotes" / "_bm" / "bm-sync.json")
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps({"assemblies": {"61": {"T1:61:01:lines": 3617}}}))
    out = tmp_path / "out"
    argv = ["assemblies", str(spec_path), "-o", str(out), "--bid", "T1"]
    assert cli.main(argv + ["--existing", str(ids)]) == 0
    assert "re-remove: 61 · 01 Rebar furnished and placed" in (out / "assemblies-report.md").read_text()
    assert cli.main(argv + ["--existing", str(tmp_path / "nope.json")]) == 2
    assert cli.main(["assemblies", str(tmp_path / "nope.yaml"), "-o", str(out), "--bid", "T1"]) == 2
    assert cli.main(argv + ["--compare", str(tmp_path / "no-dir")]) == 2
    bad = spec_two_packages()
    bad["items"][0]["labor"][0]["crew"].append({"trade": "Welder", "count": 1, "days": 1})
    spec_path.write_text(yaml.safe_dump(bad, sort_keys=False), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(argv) == 1
    assert "Welder" in capsys.readouterr().err
