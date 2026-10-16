import json

import pytest

from estimating_tools.schedule.importers import from_ganttwarrior, load_schedule

# Synthetic GanttWarrior export mirroring the real field shape (see the
# 4D staging spec; fixture is de-orged on purpose).
GW = {
    "name": "Sample OH Bridge - BL V.01",
    "description": "",
    "start_date": "2026-07-10",
    "created_at": "2026-06-03T12:00:00",
    "default_work_weekdays": [0, 1, 2, 3, 4],
    "holidays": ["2026-09-07", "2026-11-26"],
    "timezone": "America/Los_Angeles",
    "calendar_granularity": "day",
    "tasks": [
        {"id": "aaa111", "name": "OB.SUM  Bridge Summary", "wbs": "1",
         "description": "", "start_date": "2026-07-10", "end_date": "2026-09-01",
         "duration_days": 38.0, "status": "todo", "color": "#888",
         "progress": 0, "dependencies": [], "assigned_to": [], "priority": 0,
         "is_milestone": False, "parent_wbs": "", "work_days": None,
         "work_weekdays": None, "manually_edited": False, "time_blocks": [],
         "timezone": "America/Los_Angeles"},
        {"id": "bbb222", "name": "OB.1010  Finegrade for Abutment", "wbs": "1.1",
         "description": "", "start_date": "2026-07-10", "end_date": "2026-07-14",
         "duration_days": 3.0, "status": "todo", "color": "#888",
         "progress": 0, "dependencies": [], "assigned_to": [], "priority": 0,
         "is_milestone": False, "parent_wbs": "1", "work_days": None,
         "work_weekdays": None, "manually_edited": False, "time_blocks": [],
         "timezone": "America/Los_Angeles"},
        {"id": "ccc333", "name": "OB.1020  Construct Abutment Piles", "wbs": "1.2",
         "description": "", "start_date": "2026-07-15", "end_date": "2026-08-12",
         "duration_days": 21.0, "status": "todo", "color": "#888",
         "progress": 0,
         # GanttWarrior 0.2 writes the platform join key (#302). Repeated and
         # out of sorted order on purpose: the importer preserves first-seen
         # order and drops the duplicate.
         "bid_item_codes": ["31 62 00", "03 30 00", "31 62 00"],
         "dependencies": [{"predecessor_id": "bbb222",
                           "dependency_type": "FS", "lag_days": 0}],
         "assigned_to": [], "priority": 0, "is_milestone": False,
         "parent_wbs": "1", "work_days": ["2026-07-15", "2026-07-16"],
         "work_weekdays": None, "manually_edited": True, "time_blocks": [],
         "timezone": "America/Los_Angeles"},
        {"id": "ddd444", "name": "Deck complete", "wbs": "1.3",
         "description": "", "start_date": "2026-09-01", "end_date": "2026-09-01",
         "duration_days": 0.0, "status": "todo", "color": "#888",
         "progress": 0,
         "dependencies": [{"predecessor_id": "ccc333",
                           "dependency_type": "SS", "lag_days": 2}],
         "assigned_to": [], "priority": 0, "is_milestone": True,
         "parent_wbs": "1", "work_days": None, "work_weekdays": None,
         "manually_edited": False, "time_blocks": [],
         "timezone": "America/Los_Angeles"},
    ],
}


def test_from_ganttwarrior_maps_fields():
    sched = from_ganttwarrior(GW)
    assert sched.name == "Sample OH Bridge - BL V.01"
    assert sched.start_date == "2026-07-10"
    assert sched.work_weekdays == [0, 1, 2, 3, 4]
    assert sched.holidays == ["2026-09-07", "2026-11-26"]
    assert [t.id for t in sched.tasks] == ["aaa111", "bbb222", "ccc333", "ddd444"]
    t = {t.id: t for t in sched.tasks}
    assert t["bbb222"].start == "2026-07-10"
    assert t["bbb222"].finish == "2026-07-14"
    assert t["bbb222"].duration_days == 3.0
    assert t["ccc333"].dependencies[0].predecessor == "bbb222"
    assert t["ccc333"].dependencies[0].type == "FS"
    assert t["ddd444"].dependencies[0].type == "SS"
    assert t["ddd444"].dependencies[0].lag_days == 2.0
    assert t["ddd444"].is_milestone is True
    # #302: the join key survives the import, in order and de-duplicated, and a
    # task that carries no codes still lands as [] rather than failing.
    assert t["ccc333"].bid_item_codes == ["31 62 00", "03 30 00"]
    assert t["aaa111"].bid_item_codes == []


def test_from_ganttwarrior_pre_02_export_without_the_key_still_loads():
    """A pre-0.2 `.gw.json` has no `bid_item_codes` anywhere. It must load, with
    every task's codes empty — not raise, and not invent a code."""
    doc = json.loads(json.dumps(GW))
    for task in doc["tasks"]:
        task.pop("bid_item_codes", None)
    sched = from_ganttwarrior(doc)
    assert [t.bid_item_codes for t in sched.tasks] == [[], [], [], []]


def test_from_ganttwarrior_coerces_codes_to_str():
    """A code written as a number in JSON must not reach the IFC join as an int:
    element assignment compares against string classification codes."""
    doc = json.loads(json.dumps(GW))
    doc["tasks"][0]["bid_item_codes"] = [51, "51", 72]
    sched = from_ganttwarrior(doc)
    assert sched.tasks[0].bid_item_codes == ["51", "72"]


def test_from_ganttwarrior_validates():
    doc = json.loads(json.dumps(GW))
    doc["tasks"][2]["dependencies"][0]["predecessor_id"] = "nope"
    with pytest.raises(ValueError, match="unknown predecessor"):
        from_ganttwarrior(doc)


def test_load_schedule_dispatches_gw_json(tmp_path):
    p = tmp_path / "bridge.gw.json"
    p.write_text(json.dumps(GW), encoding="utf-8")
    sched = load_schedule(p)
    assert sched.name == "Sample OH Bridge - BL V.01"
    # plain .json with the gw shape also loads
    p2 = tmp_path / "bridge.json"
    p2.write_text(json.dumps(GW), encoding="utf-8")
    assert load_schedule(p2).name == sched.name


def test_load_schedule_dispatches_canonical_json(tmp_path):
    # a serialized CanonicalSchedule (canonical keys, no GanttWarrior markers)
    # routes to from_dict and PRESERVES bid_item_codes — the regression the
    # 5D cost-load surfaces depend on (a GanttWarrior wrapper drops the codes).
    p = tmp_path / "sched.json"
    p.write_text(json.dumps({
        "name": "Canonical", "work_weekdays": [0, 1, 2, 3, 4], "holidays": [],
        "tasks": [{"id": "t1", "name": "Pour", "start": "2026-08-10",
                   "finish": "2026-08-14", "bid_item_codes": ["510120"]}]}),
        encoding="utf-8")
    sched = load_schedule(p)
    assert sched.name == "Canonical"
    assert sched.tasks[0].bid_item_codes == ["510120"]
    assert sched.tasks[0].start == "2026-08-10"


def test_load_schedule_unknown_format_is_clean_error(tmp_path):
    p = tmp_path / "baseline.pdf"      # not gw.json / xer / mspdi
    p.write_text("%PDF-1.7\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported schedule format"):
        load_schedule(p)


def test_shape_detectors_tolerate_non_dict_task_entries(tmp_path):
    # a tasks list with non-object entries must not crash the format detectors
    # with an AttributeError — dispatch should still resolve cleanly.
    from estimating_tools.schedule import importers
    doc = {"name": "S", "tasks": ["not-an-object", {"start": "2026-08-10"}]}
    assert importers._looks_ganttwarrior(doc) is False
    assert importers._looks_canonical(doc) is True   # the dict task's `start` wins


def test_from_ganttwarrior_rejects_non_gw_json():
    # A JSON object with no `tasks` key is the wrong file, not an empty
    # schedule — fail loud rather than return an empty-but-valid result.
    with pytest.raises(ValueError, match="does not look like a GanttWarrior"):
        from_ganttwarrior({"organization_id": 7, "rows": []})
