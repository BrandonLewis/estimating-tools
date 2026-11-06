"""The calculating pass that stores cached values in a built workbook (#370).

openpyxl writes formulas with no cached ``<v>``: Protected View, Google Sheets
preview and ``data_only`` readers show 0 until Excel recalculates. The helper
runs the book through a calculating engine (Excel via pywin32, Excel via
PowerShell COM -- native or from WSL -- or, by name only, LibreOffice
headless), on a temp copy, and replaces the book only when the copy kept
everything the writers put there. These tests never start an engine:
availability probes, runners and ``_spawn`` are monkeypatched (the package
conftest also sets ``ESTIMATING_RECALC=off``, which they lift where they need
the chooser). The one real child process is a Python sleeper.
"""
from __future__ import annotations

import base64
import contextlib
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.packaging.custom import StringProperty
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from estimating_tools import xlsx_recalc as R


# -- fixtures ---------------------------------------------------------------------------

def _stamped_book(path: Path) -> Path:
    """A small book carrying what the writers put in: a formula, a very hidden
    ``_wb`` stamp sheet, custom properties, a defined name, four data
    validations, a hidden column and an outline level."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Items"
    ws["A1"], ws["B1"], ws["C1"] = 2, 3, "=A1*B1"
    for sqref in ("D1:D10", "D11:D20", "G1:G5"):
        dv = DataValidation(type="list", formula1='"CY,LF,EA"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(sqref)
    dv = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0")
    ws.add_data_validation(dv)
    dv.add("H1:H5")
    ws.column_dimensions["E"].hidden = True
    ws.column_dimensions["F"].outlineLevel = 1
    ws.row_dimensions[4].outlineLevel = 1
    stamp = wb.create_sheet("_wb")
    stamp["A1"] = "heavybook:1:e1"
    stamp.sheet_state = "veryHidden"
    wb.defined_names["Rate"] = DefinedName("Rate", attr_text="Items!$B$1")
    wb.custom_doc_props.append(StringProperty(name="estimate_format", value="heavybook"))
    wb.custom_doc_props.append(StringProperty(name="bidsheet_host", value="www.bidsheet.ai"))
    wb.save(path)
    return path


@pytest.fixture
def book(tmp_path):
    return _stamped_book(tmp_path / "book.xlsx")


@pytest.fixture
def engines(monkeypatch):
    """Every probe says "absent" and the off-switch is lifted; a test turns on
    the engines it wants with ``engines.have(...)`` and records runs."""
    monkeypatch.delenv(R.ENV_VAR, raising=False)
    monkeypatch.setattr(R, "_pywin32_excel", lambda: False)
    monkeypatch.setattr(R, "_powershell", lambda: None)
    monkeypatch.setattr(R, "_soffice", lambda: None)
    ran = []

    def ok(name):
        def run(tmp, timeout):
            ran.append(name)
        return run

    monkeypatch.setattr(R, "_RUNNERS", {n: ok(n) for n in R.ENGINE_NAMES})

    class E:
        runs = ran

        @staticmethod
        def have(*names):
            if "excel-com" in names:
                monkeypatch.setattr(R, "_pywin32_excel", lambda: True)
            if "excel-powershell" in names:
                monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
            if "libreoffice" in names:
                monkeypatch.setattr(R, "_soffice", lambda: "soffice")

        @staticmethod
        def runner(name, fn):
            def run(tmp, timeout):
                ran.append(name)
                return fn(tmp, timeout)
            R._RUNNERS[name] = run
    return E


def _workbook_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("xl/workbook.xml").decode("utf-8")


def _leftovers(book: Path) -> list:
    return sorted(p.name for p in book.parent.iterdir() if p.name != book.name)


def _raise(exc):
    def run(tmp, timeout):
        raise exc
    return run


# -- the chooser ------------------------------------------------------------------------

def test_no_engine_leaves_the_file_untouched_and_says_why(book, engines):
    before = book.read_bytes()
    result = R.recalculate(book)
    assert result.engine_used is None
    assert "no calculating engine" in result.reason
    assert book.read_bytes() == before
    assert engines.runs == []


def test_auto_prefers_excel_through_pywin32(book, engines):
    engines.have("excel-com", "excel-powershell", "libreoffice")
    result = R.recalculate(book)
    assert result.engine_used == "excel-com"
    assert engines.runs == ["excel-com"]


def test_auto_uses_powershell_excel_without_pywin32(book, engines):
    engines.have("excel-powershell", "libreoffice")
    assert R.recalculate(book).engine_used == "excel-powershell"


def test_auto_never_uses_libreoffice(book, engines):
    """LibreOffice has not been run on the writers' books: by name only."""
    engines.have("libreoffice")
    result = R.recalculate(book)
    assert result.engine_used is None and engines.runs == []
    assert "no calculating engine" in result.reason and "LibreOffice" not in result.reason
    assert R.AUTO_ORDER == ("excel",)


def test_explicit_engines_use_only_that_engine(book, engines):
    engines.have("excel-com", "libreoffice")
    assert R.recalculate(book, engine="libreoffice").engine_used == "libreoffice"
    assert R.recalculate(book, engine="excel").engine_used == "excel-com"
    assert engines.runs == ["libreoffice", "excel-com"]


def test_an_explicit_engine_that_is_absent_is_a_reason_not_an_error(book, engines):
    engines.have("excel-com")
    result = R.recalculate(book, engine="libreoffice")
    assert result.engine_used is None and "LibreOffice" in result.reason


def test_off_runs_nothing(book, engines):
    engines.have("excel-com")
    before = book.read_bytes()
    result = R.recalculate(book, engine="off")
    assert result.engine_used is None and "off" in result.reason
    assert engines.runs == [] and book.read_bytes() == before


def test_the_env_var_switches_every_engine_off(book, engines, monkeypatch):
    engines.have("excel-com", "excel-powershell", "libreoffice")
    monkeypatch.setenv(R.ENV_VAR, "off")
    before = book.read_bytes()
    result = R.recalculate(book, engine="excel")
    assert result.engine_used is None and R.ENV_VAR in result.reason
    assert engines.runs == [] and book.read_bytes() == before


def test_the_suite_runs_with_recalc_off():
    assert os.environ.get(R.ENV_VAR) == "off"


def test_an_unknown_engine_is_a_value_error(book, engines):
    with pytest.raises(ValueError, match="engine"):
        R.recalculate(book, engine="numbers")


def test_the_default_timeout_is_a_minute():
    assert R.DEFAULT_TIMEOUT == 60


def test_the_message_names_the_engine_or_the_reason(book, engines):
    engines.have("excel-com")
    assert "excel-com" in R.recalculate(book).message()
    line = R.recalculate(book, engine="off").message()
    assert line.startswith("RECALC:") and "off" in line
    line = R.recalculate(book, engine="libreoffice").message()
    assert "Protected View" in line and "\n" not in line


# -- which failures fall through --------------------------------------------------------

def test_excel_that_could_not_start_falls_through_to_powershell(book, engines):
    engines.have("excel-com", "excel-powershell")
    engines.runner("excel-com", _raise(R.EngineUnavailable("Class not registered")))
    result = R.recalculate(book)
    assert result.engine_used == "excel-powershell"
    assert engines.runs == ["excel-com", "excel-powershell"]


@pytest.mark.parametrize("failure", [
    R.EngineTimeout(60, 4242),
    RuntimeError("Excel crashed"),
])
def test_excel_that_ran_and_failed_ends_the_excel_attempt(book, engines, failure):
    engines.have("excel-com", "excel-powershell")
    engines.runner("excel-com", _raise(failure))
    before = book.read_bytes()
    result = R.recalculate(book)
    assert result.engine_used is None and engines.runs == ["excel-com"]
    assert book.read_bytes() == before and _leftovers(book) == []


def test_a_refused_copy_ends_the_excel_attempt(book, engines):
    engines.have("excel-com", "excel-powershell")
    engines.runner("excel-com", lambda tmp, timeout: _drop_custom_property(tmp, timeout))
    result = R.recalculate(book)
    assert result.engine_used is None and engines.runs == ["excel-com"]
    assert "estimate_format" in result.reason


def test_a_failed_replace_ends_the_excel_attempt_and_names_only_the_file(book, engines,
                                                                        monkeypatch):
    """The book is open in Excel: Windows refuses the replace (WinError 5)."""
    engines.have("excel-com", "excel-powershell")

    def denied(src, dst):
        raise PermissionError(13, "Access is denied", str(src), None, str(dst))

    monkeypatch.setattr(R.os, "replace", denied)
    before = book.read_bytes()
    result = R.recalculate(book)
    assert result.engine_used is None and engines.runs == ["excel-com"]
    assert "could not replace book.xlsx" in result.reason
    assert str(book.parent) not in result.reason
    assert book.read_bytes() == before and _leftovers(book) == []


# -- atomic replace ---------------------------------------------------------------------

def test_a_failing_engine_leaves_the_original_bytes_and_no_temp_files(book, engines):
    engines.have("excel-com")

    def boom(tmp, timeout):
        tmp.write_bytes(b"half a zip")
        raise RuntimeError(f"Excel crashed on {tmp}")

    engines.runner("excel-com", boom)
    before = book.read_bytes()
    result = R.recalculate(book)
    assert result.engine_used is None and "Excel crashed" in result.reason
    assert str(book.parent) not in result.reason and ".recalc-" in result.reason
    assert book.read_bytes() == before
    assert _leftovers(book) == []


def test_a_timeout_is_reported_and_names_the_killed_excel(book, engines):
    engines.have("excel-powershell")
    engines.runner("excel-powershell", _raise(R.EngineTimeout(5, 4242)))
    before = book.read_bytes()
    result = R.recalculate(book, timeout=5)
    assert result.engine_used is None
    assert "timed out after 5s" in result.reason and "4242" in result.reason
    assert book.read_bytes() == before


def test_a_copy_held_open_by_a_killed_excel_is_still_removed(book, engines):
    """Excel holds the temp copy (and its ``~$`` owner file) until the kill
    lands; the cleanup retries until they can go."""
    engines.have("excel-com")
    held = []
    # The "kill" lets go of both handles a moment after the timeout. On
    # Windows the open handles block the delete until then (the cleanup
    # retries); POSIX deletes an open file at once.
    release = threading.Timer(0.5, lambda: [h.close() for h in held])

    def hang(tmp, timeout):
        owner = tmp.parent / ("~$" + tmp.name)
        owner.write_bytes(b"owner")
        held.extend([open(tmp, "rb"), open(owner, "rb")])
        release.start()
        raise R.EngineTimeout(timeout, 4242)

    engines.runner("excel-com", hang)
    before = book.read_bytes()
    result = R.recalculate(book, timeout=1)
    assert "timed out" in result.reason
    release.join(5)
    assert all(h.closed for h in held)
    assert book.read_bytes() == before
    assert _leftovers(book) == []


def test_an_engine_writing_garbage_is_refused(book, engines):
    engines.have("libreoffice")
    engines.runner("libreoffice", lambda tmp, timeout: tmp.write_bytes(b"not a zip"))
    before = book.read_bytes()
    assert R.recalculate(book, engine="libreoffice").engine_used is None
    assert book.read_bytes() == before and _leftovers(book) == []


def _drop_custom_property(tmp, timeout):
    wb = load_workbook(tmp)
    wb.custom_doc_props = type(wb.custom_doc_props)()
    wb.save(tmp)


def test_an_engine_that_drops_the_stamp_is_refused(book, engines):
    engines.have("libreoffice")
    engines.runner("libreoffice", _drop_custom_property)
    before = book.read_bytes()
    result = R.recalculate(book, engine="libreoffice")
    assert result.engine_used is None
    assert "estimate_format" in result.reason
    assert book.read_bytes() == before


def _drop_validation(index):
    def damage(wb):
        dvs = wb["Items"].data_validations.dataValidation
        del dvs[index]
    return damage


@pytest.mark.parametrize("damage, word", [
    (lambda wb: wb["_wb"].__setattr__("sheet_state", "hidden"), "_wb"),
    (lambda wb: wb["_wb"].__setitem__("A1", "something else"), "_wb!A1"),
    (lambda wb: wb.defined_names.pop("Rate"), "Rate"),
    (lambda wb: setattr(wb.defined_names["Rate"], "attr_text", "Items!$A$1"),
     "defined name 'Rate' target ITEMS!B1 (now ITEMS!A1)"),
    (lambda wb: wb["Items"].data_validations.__setattr__("dataValidation", []), "validation"),
    (_drop_validation(1), "data validation (list) on Items!D11:D20"),
    (_drop_validation(3), "data validation (decimal) on Items!H1:H5"),
    (lambda wb: wb["Items"].column_dimensions["E"].__setattr__("hidden", False), "hidden column"),
    (lambda wb: wb["Items"].row_dimensions[4].__setattr__("outlineLevel", 0), "outline"),
])
def test_every_dropped_feature_is_named(book, engines, damage, word):
    engines.have("excel-com")

    def run(tmp, timeout):
        wb = load_workbook(tmp)
        damage(wb)
        wb.save(tmp)

    engines.runner("excel-com", run)
    before = book.read_bytes()
    result = R.recalculate(book)
    assert result.engine_used is None and word in result.reason
    assert book.read_bytes() == before


def test_a_name_requoted_or_reanchored_keeps_its_target(book, engines):
    """Excel may quote the sheet or drop the ``$``: same target, accepted."""
    engines.have("excel-com")

    def requote(tmp, timeout):
        wb = load_workbook(tmp)
        wb.defined_names["Rate"].attr_text = "'Items'!B1"
        wb.save(tmp)

    engines.runner("excel-com", requote)
    result = R.recalculate(book)
    assert result.engine_used == "excel-com", result.reason


def _sheet_rewrite(fn):
    def run(tmp, timeout):
        with zipfile.ZipFile(tmp) as z:
            parts = {n: z.read(n) for n in z.namelist()}
        sheet = parts["xl/worksheets/sheet1.xml"].decode("utf-8")
        parts["xl/worksheets/sheet1.xml"] = fn(sheet).encode("utf-8")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts.items():
                z.writestr(name, data)
    return run


def test_excel_merging_and_splitting_validation_ranges_is_accepted(book, engines):
    """Excel may merge D1:D10 + D11:D20 into one range and split another."""
    import re

    def regroup(sheet):
        sheet = re.sub(r'sqref="D1:D10"', 'sqref="D1:D20"', sheet)
        sheet = re.sub(r'sqref="D11:D20"', 'sqref="D5 D6"', sheet)
        return re.sub(r'sqref="G1:G5"', 'sqref="G1:G2 G3:G5"', sheet)

    engines.have("excel-com")
    engines.runner("excel-com", _sheet_rewrite(regroup))
    result = R.recalculate(book)
    assert result.engine_used == "excel-com", result.reason


_X14 = ('<extLst><ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}" '
        'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">'
        '<x14:dataValidations count="3" xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">'
        '<x14:dataValidation type="list"><x14:formula1><xm:f>Items!$A$1:$A$3</xm:f></x14:formula1>'
        '<xm:sqref>D1:D20</xm:sqref></x14:dataValidation>'
        '<x14:dataValidation type="list"><x14:formula1><xm:f>Items!$A$1:$A$3</xm:f></x14:formula1>'
        '<xm:sqref>G1:G5</xm:sqref></x14:dataValidation>'
        '<x14:dataValidation type="decimal"><x14:formula1><xm:f>0</xm:f></x14:formula1>'
        '<xm:sqref>H1:H5</xm:sqref></x14:dataValidation></x14:dataValidations></ext></extLst>')


def _move_to_x14(x14):
    import re

    def move(sheet):
        sheet = re.sub(r"<dataValidations.*?</dataValidations>", "", sheet, flags=re.S)
        return sheet.replace("</worksheet>", x14 + "</worksheet>")
    return move


def test_validations_moved_into_the_x14_extension_still_count(book, engines):
    """What Excel does to a list validation that points at a range (seen on a
    real fieldbook): it moves it into the sheet's x14 extension."""
    engines.have("excel-com")
    engines.runner("excel-com", _sheet_rewrite(_move_to_x14(_X14)))
    result = R.recalculate(book)
    assert result.engine_used == "excel-com", result.reason
    with zipfile.ZipFile(book) as z:
        assert b"x14:dataValidation " in z.read("xl/worksheets/sheet1.xml")


def test_an_x14_extension_missing_one_validation_is_refused(book, engines):
    short = _X14.replace('<xm:sqref>G1:G5</xm:sqref>', '<xm:sqref>G1:G4</xm:sqref>')
    engines.have("excel-com")
    engines.runner("excel-com", _sheet_rewrite(_move_to_x14(short)))
    before = book.read_bytes()
    result = R.recalculate(book)
    assert result.engine_used is None and "Items!G1:G5" in result.reason
    assert book.read_bytes() == before


def test_full_calc_on_load_stays_set(book, engines):
    engines.have("excel-com")

    def strip_calc(tmp, timeout):
        # Excel drops fullCalcOnLoad when it saves; the pass puts it back.
        wb = load_workbook(tmp)
        wb.calculation.fullCalcOnLoad = False
        wb.save(tmp)

    engines.runner("excel-com", strip_calc)
    assert R.recalculate(book).engine_used == "excel-com"
    assert 'fullCalcOnLoad="1"' in _workbook_xml(book)
    assert _leftovers(book) == []


def test_a_missing_file_is_a_reason(tmp_path, engines):
    engines.have("excel-com")
    result = R.recalculate(tmp_path / "nope.xlsx")
    assert result.engine_used is None and "no such file: nope.xlsx" == result.reason


# -- probes -----------------------------------------------------------------------------

def test_wsl_is_read_from_proc_version(tmp_path, monkeypatch):
    version = tmp_path / "version"
    monkeypatch.setattr(R, "_PROC_VERSION", version)
    version.write_text("Linux version 6.6.87.2-microsoft-standard-WSL2 (gcc 11.2)")
    assert R._is_wsl() is True
    version.write_text("Linux version 6.8.0-45-generic (buildd@lcy02)")
    assert R._is_wsl() is False
    version.unlink()
    assert R._is_wsl() is False


def test_powershell_is_used_under_wsl_when_on_path(monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "linux")
    monkeypatch.setattr(R, "_is_wsl", lambda: True)
    monkeypatch.setattr(R.shutil, "which", lambda name: "/mnt/c/WINDOWS/powershell.exe"
                        if name == "powershell.exe" else None)
    assert R._powershell() == "/mnt/c/WINDOWS/powershell.exe"
    monkeypatch.setattr(R, "_is_wsl", lambda: False)
    assert R._powershell() is None


# -- children: the timeout kills what they started --------------------------------------

_SLEEPER_PARENT = """import subprocess, sys, time
sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(f"EXCEL_PID={sleeper.pid}", flush=True)
time.sleep(60)
"""


def test_a_timeout_kills_the_child_and_the_excel_it_reported(monkeypatch):
    """DCOM starts Excel outside the child's tree: killing the child alone
    leaves Excel running. The child's ``EXCEL_PID=`` line names it."""
    killed = []

    def kill(pid):
        killed.append(pid)
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            # The process-group kill may already have ended it.
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, 9)

    monkeypatch.setattr(R, "_kill_pid", kill)
    with pytest.raises(R.EngineTimeout) as exc:
        R._spawn([sys.executable, "-c", _SLEEPER_PARENT], timeout=3)
    assert exc.value.pid and killed == [exc.value.pid]


def test_a_timeout_before_the_pid_line_kills_the_new_automation_excel(monkeypatch):
    """The timeout came while COM was still starting Excel: no pid line. The
    automation Excels that appeared meanwhile are the child's; an Excel the
    estimator opened (no ``/automation``) and one already running are left."""
    snapshots = iter([{100}, {100, 200, 300}])
    monkeypatch.setattr(R, "_excel_pids", lambda: next(snapshots))
    monkeypatch.setattr(R, "_automation_only", lambda pids: {p for p in pids if p == 300})
    killed = []
    monkeypatch.setattr(R, "_kill_pid", killed.append)
    with pytest.raises(R.EngineTimeout) as exc:
        R._spawn([sys.executable, "-c", "import time; time.sleep(60)"], timeout=2, excel=True)
    assert killed == [300] and exc.value.pid == 300


def test_a_timeout_without_excel_kills_no_excel(monkeypatch):
    monkeypatch.setattr(R, "_excel_pids", lambda: pytest.fail("looked for Excel"))
    monkeypatch.setattr(R, "_kill_pid", lambda pid: pytest.fail("killed"))
    with pytest.raises(R.EngineTimeout) as exc:
        R._spawn([sys.executable, "-c", "import time; time.sleep(60)"], timeout=2)
    assert exc.value.pid is None


_TASKLIST = ('"EXCEL.EXE","23788","Console","1","242,372 K"\r\n'
             '"EXCEL.EXE","71392","Console","1","234,320 K"\r\n')
_CIM = ('200 "C:\\Office16\\EXCEL.EXE" /automation -Embedding\n'
        '300 "C:\\Office16\\EXCEL.EXE" "C:\\bids\\mine.xlsx"\n'
        '400 "C:\\Office16\\EXCEL.EXE" /automation -Embedding\n')


def _stdout(text):
    return lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=text, stderr="")


def test_tasklist_output_is_parsed(monkeypatch):
    monkeypatch.setattr(R, "_tasklist", lambda: "tasklist")
    monkeypatch.setattr(R.subprocess, "run", _stdout(_TASKLIST))
    assert R._excel_pids() == {23788, 71392}
    monkeypatch.setattr(R.subprocess, "run", _stdout(
        "INFO: No tasks are running which match the specified criteria.\r\n"))
    assert R._excel_pids() == set()


def test_only_automation_excels_are_candidates(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda name: "powershell.exe")
    monkeypatch.setattr(R.subprocess, "run", _stdout(_CIM))
    assert R._automation_only({200, 300}) == {200}


def test_an_excel_opened_on_an_automation_path_is_not_a_candidate(monkeypatch):
    """Only the COM switch pair counts, not "/automation" anywhere."""
    monkeypatch.setattr(R.shutil, "which", lambda name: "powershell.exe")
    monkeypatch.setattr(R.subprocess, "run", _stdout(
        '500 "C:\\Office16\\EXCEL.EXE" "//server/automation/bid.xlsx"\n'
        '501 "C:\\Office16\\EXCEL.EXE" "C:/jobs/automation -embedding notes.xlsx"\n'
        '502 "C:\\Office16\\EXCEL.EXE" /automation -Embedding\n'))
    assert R._automation_only({500, 501, 502}) == {502}


def test_a_child_that_returns_in_time_is_not_killed(monkeypatch):
    monkeypatch.setattr(R, "_kill_pid", lambda pid: pytest.fail("killed"))
    rc, out, err = R._spawn([sys.executable, "-c", "print('EXCEL_PID=7'); print('done')"], 30)
    assert rc == 0 and "done" in out


def test_exit_3_means_excel_could_not_start():
    with pytest.raises(R.EngineUnavailable, match="ActiveX"):
        R._check(3, "EXCEL_PID=0\n", "Cannot create ActiveX component.")
    with pytest.raises(RuntimeError, match="Workbooks.Open"):
        R._check(1, "EXCEL_PID=99\n", "Exception calling Workbooks.Open")


# -- runners' commands (_spawn faked) ---------------------------------------------------

def _fake_spawn(monkeypatch, result=(0, "", ""), effect=None):
    seen = {}

    def spawn(argv, timeout, **kw):
        seen["argv"], seen["timeout"] = argv, timeout
        if effect:
            effect(argv)
        return result

    monkeypatch.setattr(R, "_spawn", spawn)
    return seen


def _ps_script(argv) -> str:
    return base64.b64decode(argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")


def test_the_wsl_powershell_runner_translates_the_path(tmp_path, monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "linux")
    monkeypatch.setattr(R, "_powershell", lambda: "/mnt/c/WINDOWS/powershell.exe")
    wsl = []

    def fake_run(argv, **kw):
        wsl.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="C:\\Users\\me\\it's.xlsx\n",
                                           stderr="")

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    seen = _fake_spawn(monkeypatch)
    R._run_powershell(tmp_path / "it's.xlsx", 30)
    assert wsl[0][:2] == ["wslpath", "-w"]
    assert seen["argv"][0] == "/mnt/c/WINDOWS/powershell.exe" and seen["timeout"] == 30
    script = _ps_script(seen["argv"])
    # The path is a single-quoted PowerShell literal: a quote inside is doubled.
    assert "'C:\\Users\\me\\it''s.xlsx'" in script
    assert "CalculateFullRebuild" in script and ".Save()" in script and ".Quit()" in script
    assert "EXCEL_PID=" in script and "GetWindowThreadProcessId" in script


def test_curly_quotes_are_doubled_in_the_powershell_path(tmp_path, monkeypatch):
    """PowerShell ends a single-quoted string at U+2018..U+201B too."""
    monkeypatch.setattr(R.sys, "platform", "win32")
    monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(R, "_windows_path", lambda p: "C:\\Bids\\O\u2019Brien \u2018x\u201b.xlsx")
    seen = _fake_spawn(monkeypatch)
    R._run_powershell(tmp_path / "b.xlsx", 30)
    assert "'C:\\Bids\\O\u2019\u2019Brien \u2018\u2018x\u201b\u201b.xlsx'" in _ps_script(seen["argv"])


def test_a_powershell_failure_raises_with_its_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "win32")
    monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
    _fake_spawn(monkeypatch, result=(1, "", "Exception calling Open"))
    with pytest.raises(RuntimeError, match="calling Open"):
        R._run_powershell(tmp_path / "b.xlsx", 30)
    _fake_spawn(monkeypatch, result=(3, "", "Cannot create ActiveX component."))
    with pytest.raises(R.EngineUnavailable):
        R._run_powershell(tmp_path / "b.xlsx", 30)


def test_the_libreoffice_runner_converts_into_a_temp_dir(book, monkeypatch):
    monkeypatch.setattr(R, "_soffice", lambda: "/usr/bin/soffice")
    xcu = {}

    def effect(argv):
        outdir = Path(argv[argv.index("--outdir") + 1])
        profile = next(a for a in argv if a.startswith("-env:UserInstallation="))
        path = Path(R._uri_to_path(profile.split("=", 1)[1])) / "user" / "registrymodifications.xcu"
        xcu["text"] = path.read_text(encoding="utf-8")
        src = Path(argv[-1])
        shutil.copyfile(src, outdir / src.name)

    seen = _fake_spawn(monkeypatch, effect=effect)
    R._run_soffice(book, 60)
    argv = seen["argv"]
    assert argv[0] == "/usr/bin/soffice" and "--headless" in argv and "--calc" in argv
    assert argv[argv.index("--convert-to") + 1].startswith("xlsx")
    assert seen["timeout"] == 60
    assert "OOXMLRecalcMode" in xcu["text"]


def test_the_libreoffice_runner_raises_when_nothing_was_written(book, monkeypatch):
    monkeypatch.setattr(R, "_soffice", lambda: "soffice")
    _fake_spawn(monkeypatch, result=(0, "", "source file could not be loaded"))
    before = book.read_bytes()
    with pytest.raises(RuntimeError, match="could not be loaded"):
        R._run_soffice(book, 60)
    assert book.read_bytes() == before


def test_a_libreoffice_timeout_is_not_masked_by_cleanup(book, monkeypatch):
    monkeypatch.setattr(R, "_soffice", lambda: "soffice")
    held = []

    def spawn(argv, timeout, **kw):
        outdir = Path(argv[argv.index("--outdir") + 1])
        held.append(open(outdir / "lock", "wb"))   # a killed soffice still holding it
        raise R.EngineTimeout(timeout)

    monkeypatch.setattr(R, "_spawn", spawn)
    try:
        with pytest.raises(R.EngineTimeout):
            R._run_soffice(book, 1)
    finally:
        for h in held:
            h.close()


def test_the_pywin32_runner_runs_excel_in_a_child_process(tmp_path, monkeypatch):
    seen = _fake_spawn(monkeypatch)
    R._run_pywin32(tmp_path / "b.xlsx", 45)
    assert seen["argv"][0] == R.sys.executable and seen["timeout"] == 45
    assert "calcbook.recalc" in seen["argv"][2] and "EXCEL_PID=" in seen["argv"][2]
    assert seen["argv"][-1] == str(tmp_path / "b.xlsx")


# -- a real LibreOffice pass ------------------------------------------------------------

@pytest.mark.skipif(R._soffice() is None, reason="LibreOffice (soffice) is not installed")
def test_libreoffice_keeps_the_stamp_names_and_validations(book, monkeypatch):
    monkeypatch.delenv(R.ENV_VAR, raising=False)
    result = R.recalculate(book, engine="libreoffice")
    assert result.engine_used == "libreoffice", result.reason
    wb = load_workbook(book)
    assert wb["_wb"]["A1"].value == "heavybook:1:e1"
    assert wb["_wb"].sheet_state == "veryHidden"
    props = {p.name: p.value for p in wb.custom_doc_props}
    assert props["estimate_format"] == "heavybook"
    assert props["bidsheet_host"] == "www.bidsheet.ai"
    assert "Rate" in wb.defined_names
    assert wb["Items"].data_validations.dataValidation
    assert wb["Items"]["C1"].value == "=A1*B1"
    assert load_workbook(book, data_only=True)["Items"]["C1"].value == 6
    assert 'fullCalcOnLoad="1"' in _workbook_xml(book)
