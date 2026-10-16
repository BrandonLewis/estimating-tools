"""P6 XER and MS Project MSPDI importers → CanonicalSchedule (slice 4)."""
from pathlib import Path

import pytest

from estimating_tools.schedule.importers import (
    from_mspdi, from_xer, load_schedule,
)

FIX = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# XER
# ---------------------------------------------------------------------------

def test_from_xer_tasks_dates_wbs_and_milestone():
    sched = from_xer((FIX / "mini.xer").read_text(encoding="cp1252"))
    assert sched.name == "Sample Bridge"
    assert sched.start_date == "2026-07-10"
    by_id = {t.id: t for t in sched.tasks}
    # activities keyed by task_code; two WBS summaries synthesized
    assert "A1010" in by_id and "B1099" in by_id
    assert by_id["A1010"].start == "2026-07-10"
    assert by_id["A1010"].finish == "2026-07-14"
    assert by_id["B1099"].is_milestone is True
    # WBS: substructure summary "1" with activities nested "1.x"
    subs = [t for t in sched.tasks if t.name == "Substructure"]
    assert subs and subs[0].wbs
    assert by_id["A1010"].wbs.startswith(subs[0].wbs + ".")
    assert subs[0].id in sched.summary_ids()


def test_from_xer_dependencies_type_and_lag():
    sched = from_xer((FIX / "mini.xer").read_text(encoding="cp1252"))
    by_id = {t.id: t for t in sched.tasks}
    # A1020 FS A1010, lag 0
    dep = by_id["A1020"].dependencies[0]
    assert dep.predecessor == "A1010" and dep.type == "FS" and dep.lag_days == 0
    # B1010 FS A1020 with 16 lag-hours -> 2 work-days
    dep = by_id["B1010"].dependencies[0]
    assert dep.predecessor == "A1020" and dep.lag_days == 2.0


def test_from_xer_validates():
    from_xer((FIX / "mini.xer").read_text(encoding="cp1252")).validate()


def test_from_xer_activity_codes_joined_type_colon_name():
    # ACTVTYPE "Subcontractor" + ACTVCODE "SUB-A" joined through TASKACTV land
    # on the task as "<type>: <name>"; tasks with no TASKACTV row carry [].
    sched = from_xer((FIX / "mini.xer").read_text(encoding="cp1252"))
    by_id = {t.id: t for t in sched.tasks}
    assert by_id["A1010"].activity_codes == ["Subcontractor: SUB-A"]
    assert by_id["A1020"].activity_codes == []
    assert by_id["B1010"].activity_codes == []


def test_from_xer_emits_intermediate_wbs_summaries():
    # WBS "1" has child WBS nodes with activities but no direct activities of
    # its own — it must still appear as a summary task and nest its children.
    xer = (
        "%T\tPROJECT\n%F\tproj_id\tproj_short_name\tplan_start_date\n"
        "%R\t1\tBridge\t2026-07-10 08:00\n"
        "%T\tPROJWBS\n%F\twbs_id\tproj_id\tparent_wbs_id\tseq_num\twbs_name\tproj_node_flag\n"
        "%R\t100\t1\t\t0\tBridge\tY\n"
        "%R\t110\t1\t100\t1\tSubstructure\tN\n"        # intermediate, no direct tasks
        "%R\t111\t1\t110\t1\tAbutments\tN\n"           # leaf WBS with the activity
        "%T\tTASK\n%F\ttask_id\tproj_id\twbs_id\ttask_code\ttask_name\ttask_type\t"
        "target_drtn_hr_cnt\tact_start_date\tact_end_date\tearly_start_date\t"
        "early_end_date\ttarget_start_date\ttarget_end_date\n"
        "%R\t1001\t1\t111\tA1\tPour abutment\tTT_Task\t8\t\t\t2026-07-10 08:00\t"
        "2026-07-11 17:00\t2026-07-10 08:00\t2026-07-11 17:00\n"
    )
    sched = from_xer(xer)
    by_wbs = {t.wbs: t for t in sched.tasks}
    assert "1" in by_wbs and by_wbs["1"].name == "Substructure"
    assert "1.1" in by_wbs and by_wbs["1.1"].name == "Abutments"
    # both intermediate nodes are summaries (ancestors of the activity 1.1.1)
    assert {by_wbs["1"].id, by_wbs["1.1"].id} <= sched.summary_ids()


# ---------------------------------------------------------------------------
# MSPDI
# ---------------------------------------------------------------------------

def test_from_mspdi_tasks_outline_wbs_and_milestone():
    sched = from_mspdi((FIX / "mini.mspdi.xml").read_text(encoding="utf-8"))
    assert sched.name == "Sample Bridge MSP"
    assert sched.start_date == "2026-07-10"
    by_id = {t.id: t for t in sched.tasks}
    # UID 0 (project summary) is dropped; tasks keyed by UID
    assert "0" not in by_id
    assert by_id["2"].name == "Drill abutment piles"
    assert by_id["2"].wbs == "1.1"          # OutlineNumber verbatim
    assert by_id["4"].is_milestone is True
    assert by_id["1"].id in sched.summary_ids()   # Substructure (1) parents 1.1/1.2


def test_from_mspdi_dependencies_type_and_lag():
    sched = from_mspdi((FIX / "mini.mspdi.xml").read_text(encoding="utf-8"))
    by_id = {t.id: t for t in sched.tasks}
    assert by_id["3"].dependencies[0].predecessor == "2"
    assert by_id["3"].dependencies[0].type == "FS"    # MSPDI Type 1
    assert by_id["3"].dependencies[0].lag_days == 0
    # LinkLag 4800 tenths-of-minutes at 8h/day -> 1 work-day
    assert by_id["4"].dependencies[0].lag_days == 1.0


def test_from_mspdi_validates():
    from_mspdi((FIX / "mini.mspdi.xml").read_bytes()).validate()


def test_from_mspdi_resource_assignments_names_in_document_order():
    # Resources UID->Name joined through Assignments TaskUID: task 2 carries
    # both crews in document order, task 3 one, milestone 4 none.
    sched = from_mspdi((FIX / "mini.mspdi.xml").read_bytes())
    by_id = {t.id: t for t in sched.tasks}
    assert by_id["2"].resources == ["Pile Crew", "Concrete Crew"]
    assert by_id["3"].resources == ["Concrete Crew"]
    assert by_id["4"].resources == []
    assert by_id["1"].resources == []


def test_from_mspdi_honors_prolog_encoding_utf16():
    # MS Project exports are frequently UTF-16 on Windows; passing bytes lets
    # ElementTree honor the prolog rather than mis-decoding as UTF-8.
    xml = ('<?xml version="1.0" encoding="UTF-16"?>'
           '<Project xmlns="http://schemas.microsoft.com/project">'
           '<Name>UTF16 Bridge</Name><StartDate>2026-07-10T08:00:00</StartDate>'
           '<Tasks><Task><UID>1</UID><Name>Task A</Name>'
           '<OutlineNumber>1</OutlineNumber><Milestone>0</Milestone>'
           '<Start>2026-07-10T08:00:00</Start><Finish>2026-07-11T17:00:00</Finish>'
           '</Task></Tasks></Project>')
    sched = from_mspdi(xml.encode("utf-16"))
    assert sched.name == "UTF16 Bridge"
    assert sched.tasks[0].name == "Task A"


def test_from_mspdi_non_mspdi_is_clean_error():
    with pytest.raises(ValueError, match="not an\\s+MSPDI|no <Tasks>"):
        from_mspdi(b'<?xml version="1.0"?><foo><bar/></foo>')


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def test_load_schedule_dispatches_xer_and_mspdi(tmp_path):
    assert load_schedule(FIX / "mini.xer").name == "Sample Bridge"
    assert load_schedule(FIX / "mini.mspdi.xml").name == "Sample Bridge MSP"


def test_from_xer_missing_tables_is_clean_error():
    with pytest.raises(ValueError, match="no TASK"):
        from_xer("ERMHDR\t20.12\n%T\tPROJECT\n%F\tproj_id\n%R\t1\n%E\n")
