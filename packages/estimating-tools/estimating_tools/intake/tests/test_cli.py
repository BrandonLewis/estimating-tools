"""est-intake init / register / bid-frame / briefing, end to end on tmp dirs."""
import json

import yaml

from estimating_tools.intake.cli import main
from estimating_tools.intake.manifest import ProjectManifest

BID_DIR = "B1042-2026-07-16"


def _init(tmp_path):
    rc = main(["init", "Job X", "--parent", str(tmp_path),
               "--bid-number", "1042", "--bid-date", "2026-07-16",
               "--organization-id", "7", "--bm-project-id", "42",
               "--project-ref", "job-x"])
    assert rc == 0
    return tmp_path / "Job X"


def test_init_scaffolds_project_and_bid_dirs(tmp_path):
    proj = _init(tmp_path)
    assert (proj / "Plans").is_dir()
    assert (proj / BID_DIR / "Estimate").is_dir()
    assert (proj / BID_DIR / "Briefing" / "prompts").is_dir()
    m = ProjectManifest.load(proj / "manifest.json")
    assert (m.name, m.organization_id, m.bm_project_id) == ("Job X", 7, 42)
    assert m.bid_dir == BID_DIR


def test_init_without_bid_number_makes_project_only(tmp_path):
    rc = main(["init", "Job Y", "--parent", str(tmp_path)])
    assert rc == 0
    proj = tmp_path / "Job Y"
    assert (proj / "Plans").is_dir()
    m = ProjectManifest.load(proj / "manifest.json")
    assert m.bid_dir is None


def test_init_twice_errors_without_clobbering(tmp_path):
    proj = _init(tmp_path)
    (proj / "manifest.json").write_text('{"name": "edited"}', encoding="utf-8")
    rc = main(["init", "Job X", "--parent", str(tmp_path)])
    assert rc == 1  # refuses: manifest already exists
    assert json.loads((proj / "manifest.json").read_text())["name"] == "edited"


def test_init_is_safe_over_existing_work_cli_dirs(tmp_path):
    (tmp_path / "Job X" / BID_DIR / "Estimate").mkdir(parents=True)
    seeded = tmp_path / "Job X" / BID_DIR / "B1042-TakeOff.xlsx"
    seeded.write_bytes(b"xlsx")
    proj = _init(tmp_path)
    assert seeded.read_bytes() == b"xlsx"   # work-CLI-seeded file untouched
    assert (proj / BID_DIR / "Takeoff").is_dir()


def test_register_hashes_and_records(tmp_path):
    proj = _init(tmp_path)
    f = proj / "Plans" / "set1.pdf"
    f.write_bytes(b"%PDF-fake")
    rc = main(["register", str(proj), str(f), "--kind", "plans", "--source", "local"])
    assert rc == 0
    m = ProjectManifest.load(proj / "manifest.json")
    assert m.documents[0].path == "Plans/set1.pdf"
    assert len(m.documents[0].sha256) == 64


def test_bid_frame_snapshots_and_seeds_takeoff_map(tmp_path):
    proj = _init(tmp_path)
    items = [{"id": 901, "item_number": "0010", "schedule_name": "A",
              "item_code": "03 30 00", "description": "Concrete", "unit": "CY"}]
    raw = tmp_path / "items.json"
    raw.write_text(json.dumps(items), encoding="utf-8")
    rc = main(["bid-frame", str(proj), "--items", str(raw)])
    assert rc == 0
    m = ProjectManifest.load(proj / "manifest.json")
    assert m.bid_frame[0].item_number == "0010"
    skel = yaml.safe_load(
        (proj / BID_DIR / "Takeoff" / "takeoff_map.skel.yaml").read_text(encoding="utf-8"))
    assert skel["codes"]["03 30 00"]["item_number"] == "0010"


def test_bid_frame_invalid_items_fail_cleanly(tmp_path):
    proj = _init(tmp_path)
    raw = tmp_path / "items.json"
    raw.write_text(json.dumps([{"id": 9}]), encoding="utf-8")   # no item_number
    rc = main(["bid-frame", str(proj), "--items", str(raw)])
    assert rc == 1


def test_briefing_builds_pack_in_bid_dir(tmp_path):
    proj = _init(tmp_path)
    structures = {"structures": [{"id": "s1", "name": "Structure 1"}]}
    sfile = tmp_path / "structures.yaml"
    sfile.write_text(yaml.safe_dump(structures), encoding="utf-8")
    rc = main(["briefing", str(proj), "--structures", str(sfile)])
    assert rc == 0
    assert (proj / BID_DIR / "Briefing" / "prompts" / "s1.md").exists()


def test_briefing_invalid_id_fails_cleanly(tmp_path):
    proj = _init(tmp_path)
    sfile = tmp_path / "structures.yaml"
    sfile.write_text(yaml.safe_dump({"structures": [{"id": "../evil"}]}), encoding="utf-8")
    rc = main(["briefing", str(proj), "--structures", str(sfile)])
    assert rc == 1


def test_bid_stage_commands_require_bid_dir(tmp_path):
    main(["init", "Job Y", "--parent", str(tmp_path)])
    sfile = tmp_path / "structures.yaml"
    sfile.write_text(yaml.safe_dump({"structures": []}), encoding="utf-8")
    rc = main(["briefing", str(tmp_path / "Job Y"), "--structures", str(sfile)])
    assert rc == 1  # no bid dir on the manifest


def test_commands_without_manifest_fail_cleanly(tmp_path):
    rc = main(["bid-frame", str(tmp_path), "--items", str(tmp_path / "x.json")])
    assert rc == 1


def test_init_rejects_path_separator_bid_number(tmp_path):
    rc = main(["init", "Job Z", "--parent", str(tmp_path),
               "--bid-number", "22/06", "--bid-date", "2026-07-16"])
    assert rc == 1
    assert not (tmp_path / "Job Z").exists()   # rejected before any writes


def test_init_rejects_bad_bid_date(tmp_path):
    rc = main(["init", "Job Z", "--parent", str(tmp_path),
               "--bid-number", "1042", "--bid-date", "07-16-2026"])
    assert rc == 1


def test_register_outside_project_fails_cleanly(tmp_path):
    proj = _init(tmp_path)
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"x")
    rc = main(["register", str(proj), str(outside), "--kind", "plans"])
    assert rc == 1


def test_register_missing_file_fails_cleanly(tmp_path):
    proj = _init(tmp_path)
    rc = main(["register", str(proj), str(proj / "Plans" / "nope.pdf"), "--kind", "plans"])
    assert rc == 1


def test_bid_frame_malformed_json_fails_cleanly(tmp_path):
    proj = _init(tmp_path)
    raw = tmp_path / "items.json"
    raw.write_text("{not json", encoding="utf-8")
    rc = main(["bid-frame", str(proj), "--items", str(raw)])
    assert rc == 1


def test_bid_frame_rejects_non_list_json(tmp_path):
    proj = _init(tmp_path)
    raw = tmp_path / "items.json"
    raw.write_text('{"items": []}', encoding="utf-8")
    rc = main(["bid-frame", str(proj), "--items", str(raw)])
    assert rc == 1


def test_briefing_rejects_non_mapping_yaml(tmp_path):
    proj = _init(tmp_path)
    sfile = tmp_path / "structures.yaml"
    sfile.write_text("- just\n- a\n- list\n", encoding="utf-8")
    rc = main(["briefing", str(proj), "--structures", str(sfile)])
    assert rc == 1


def test_escaping_bid_dir_in_manifest_rejected(tmp_path):
    proj = _init(tmp_path)
    m = json.loads((proj / "manifest.json").read_text(encoding="utf-8"))
    m["bid_dir"] = "../escape"
    (proj / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    sfile = tmp_path / "structures.yaml"
    sfile.write_text(yaml.safe_dump({"structures": [{"id": "s1"}]}), encoding="utf-8")
    rc = main(["briefing", str(proj), "--structures", str(sfile)])
    assert rc == 1
    items = tmp_path / "items.json"
    items.write_text(json.dumps([{"id": 1, "item_number": "0010",
                                  "schedule_name": "A", "item_code": "03 30 00",
                                  "unit": "CY"}]), encoding="utf-8")
    rc = main(["bid-frame", str(proj), "--items", str(items)])
    assert rc == 1
    assert not (tmp_path / "escape").exists()
