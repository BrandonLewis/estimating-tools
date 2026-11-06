"""A calculating pass that stores cached values in a built workbook (#370).

Opt-in: the builds, patches and refreshes already store cached values with
the built-in evaluator (:mod:`estimating_tools.xlcalc`, #445), so the CLIs run
this pass only when asked (``--recalc excel``, ``auto`` or ``libreoffice``;
the default is ``off``). It is for functions the built-in evaluator does not
cover, or a book Excel itself should have computed.

openpyxl writes every formula with no cached ``<v>`` value. Excel recalculates
on open -- but not in Protected View (a book from a download, an email or a
network share), and Google Sheets preview, Numbers, ``data_only`` readers and
the artifact editor never do: every computed cell reads 0 or blank. A
reviewer saw "0 CY" on a row that was really 293 CY.

:func:`recalculate` runs the saved book through a calculating engine, which
keeps the formulas live and stores their values. ``auto`` uses Excel only:

1. ``excel-com`` -- Excel through pywin32 (Windows), in a child process so it
   can be timed out (:mod:`estimating_tools.calcbook.recalc` drives it);
2. ``excel-powershell`` -- Excel through PowerShell COM: under WSL
   (``/proc/version`` says microsoft and ``powershell.exe`` is on PATH; the
   path goes through ``wslpath -w``), or native Windows without pywin32.

The second is tried only when the first could not start Excel at all; a
timeout, a refused copy or a failed replace ends the Excel attempt (a second
Excel would meet the same book, or hang the same way).

``libreoffice`` -- ``soffice --headless --convert-to xlsx`` into a temp dir,
with a throwaway profile that tells Calc to recalculate on load -- runs only
when asked for by name: it has not been run against the writers' books yet,
and it rewrites the whole package.

The engine works on a temp copy beside the book. The child reports the Excel
process it started (``EXCEL_PID=n`` on its first line); on a timeout the child
and that Excel are killed -- DCOM starts Excel outside the child's process
tree, so killing the child alone leaves a hidden Excel holding the copy --
and the copy and Excel's ``~$`` owner file are removed. The copy replaces the
book (``os.replace``, atomic) only when it is a readable package that kept
every custom document property, defined name, sheet state, data validation
(by type and covered cells, in either namespace: Excel moves a range list
into the x14 extension), hidden column, outline level and hidden-sheet ``A1``
stamp of the original; ``fullCalcOnLoad`` is set on it again (Excel drops it
when it saves), so Excel still recalculates on open. Anything else -- no
engine, an engine that fails, times out or drops something -- leaves the book
byte-for-byte as written and says why in :attr:`RecalcResult.reason`. Nothing
here raises for "no engine".

A recalculated book is not byte-reproducible (Excel writes ids and its own
metadata); only ``off`` keeps a rebuild byte-identical.

``ESTIMATING_RECALC=off`` switches every engine off whatever the caller asked
(the test suite sets it, so no test shells out).
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from xml.etree import ElementTree as ET

ENV_VAR = "ESTIMATING_RECALC"
#: What ``--recalc`` accepts.
CHOICES = ("auto", "excel", "libreoffice", "off")
#: Every engine.
ENGINE_NAMES = ("excel-com", "excel-powershell", "libreoffice")
_FAMILIES = {"excel": ("excel-com", "excel-powershell"), "libreoffice": ("libreoffice",)}
#: The families ``auto`` uses: Excel only until LibreOffice has been run on real books.
AUTO_ORDER = ("excel",)
DEFAULT_TIMEOUT = 60
_PROC_VERSION = Path("/proc/version")
#: Exit code a child uses for "Excel could not be started".
_UNAVAILABLE_EXIT = 3
_PID_LINE = re.compile(r"^EXCEL_PID=(\d+)\s*$", re.M)

_LABEL = {"excel-com": "Excel (pywin32)", "excel-powershell": "Excel (PowerShell COM)",
          "libreoffice": "LibreOffice (soffice)"}


@dataclass(frozen=True)
class RecalcResult:
    """``engine_used`` is the engine that stored the values, or None when the
    book was left as written; ``reason`` says what happened either way."""
    engine_used: str | None
    reason: str

    def message(self) -> str:
        """The one line a CLI prints."""
        if self.engine_used:
            return f"RECALC: {self.engine_used} stored cached values ({self.reason})"
        if self.reason.startswith("off"):
            return f"RECALC: {self.reason}"
        return (f"RECALC: none -- {self.reason}; formulas are live and Excel computes "
                "them on open, but Protected View shows 0 until editing is enabled")


class EngineUnavailable(RuntimeError):
    """The engine could not start (no pywin32, COM could not create Excel):
    nothing ran, so the next engine of the family may try."""


class EngineTimeout(RuntimeError):
    """The engine ran past its timeout; the child and the Excel it reported
    were killed."""

    def __init__(self, timeout: float, pid: int | None = None):
        super().__init__(f"timed out after {timeout:g}s")
        self.timeout, self.pid = timeout, pid


# -- availability probes (monkeypatched in tests) ---------------------------------------

def _excel_registered() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Excel.Application"))
    except OSError:
        return False
    return True


def _pywin32_excel() -> bool:
    if sys.platform != "win32":
        return False
    try:
        found = importlib.util.find_spec("win32com") is not None
    except (ImportError, ValueError):
        found = False
    return found and _excel_registered()


def _is_wsl() -> bool:
    try:
        return "microsoft" in _PROC_VERSION.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False


def _powershell() -> str | None:
    """powershell.exe when Excel can be reached through it: under WSL, or on
    Windows with Excel registered."""
    if sys.platform == "win32":
        exe = shutil.which("powershell.exe") or shutil.which("powershell")
        return exe if exe and _excel_registered() else None
    if _is_wsl():
        return shutil.which("powershell.exe")
    return None


def _soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        exe = shutil.which(name)
        if exe:
            return exe
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                exe = Path(root) / "LibreOffice" / "program" / "soffice.exe"
                if exe.exists():
                    return str(exe)
    return None


def _available(name: str) -> bool:
    if name == "excel-com":
        return _pywin32_excel()
    if name == "excel-powershell":
        return _powershell() is not None
    return _soffice() is not None


# -- children: run with a timeout, and on a timeout kill what they started -------------

def _taskkill() -> str | None:
    if sys.platform == "win32":
        return shutil.which("taskkill") or "taskkill"
    return shutil.which("taskkill.exe") if _is_wsl() else None


def _kill_pid(pid: int) -> None:
    """Kill a Windows process (the Excel a child started) and its tree."""
    exe = _taskkill()
    if not exe:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run([exe, "/PID", str(pid), "/F", "/T"], capture_output=True, timeout=30)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill a child and everything it started (soffice.exe starts soffice.bin)."""
    if sys.platform == "win32":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/F", "/T"],
                           capture_output=True, timeout=30)
    else:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _reported_pid(out: str) -> int | None:
    m = _PID_LINE.search(out or "")
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def _tasklist() -> str | None:
    if sys.platform == "win32":
        return shutil.which("tasklist") or "tasklist"
    return shutil.which("tasklist.exe") if _is_wsl() else None


def _excel_pids() -> set:
    """The running EXCEL.EXE process ids (empty off Windows/WSL)."""
    exe = _tasklist()
    if not exe:
        return set()
    try:
        out = subprocess.run([exe, "/FI", "IMAGENAME eq EXCEL.EXE", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    pids = set()
    for line in out.splitlines():
        cells = [c.strip('"') for c in line.strip().split('","')]
        if len(cells) > 1 and cells[0].upper().startswith("EXCEL") and cells[1].isdigit():
            pids.add(int(cells[1]))
    return pids


#: The switch pair COM starts Excel with; a path containing "/automation" on
#: an Excel the estimator opened does not match it.
_AUTOMATION = re.compile(r"(?:^|\s)/automation\s+-embedding(?:\s|$)", re.I)


def _automation_only(pids: set) -> set:
    """Of ``pids``, the Excels COM started (``/automation -Embedding``): an
    Excel the estimator opened is never one of them."""
    exe = shutil.which("powershell.exe") or shutil.which("powershell")
    if not pids or not exe:
        return set()
    query = ("Get-CimInstance Win32_Process -Filter \"Name='EXCEL.EXE'\" | "
             "ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }")
    try:
        out = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", query],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    found = set()
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid.isdigit() and int(pid) in pids and _AUTOMATION.search(cmd):
            found.add(int(pid))
    return found


def _new_excels(before: set, wait: float = 5.0) -> set:
    """Automation Excels started since ``before``; waits a little, since an
    Excel whose start the timeout interrupted may still be coming up."""
    deadline = time.monotonic() + wait
    while True:
        new = _excel_pids() - before
        if new or time.monotonic() >= deadline:
            return _automation_only(new)
        time.sleep(0.5)


def _spawn(argv: list, timeout: float, *, excel: bool = False) -> tuple:
    """Run ``argv``; return ``(returncode, stdout, stderr)``. On a timeout kill
    the child's tree and the Excel it started, then raise EngineTimeout.

    ``excel``: the child starts an Excel through COM. It names it on its first
    line (``EXCEL_PID=n``); when the timeout came before that line, the
    automation Excels that appeared while the child ran are the ones it
    started.

    Caveat of that fallback: if the timeout fires before the child prints its
    pid (Excel took longer than the timeout to start), every automation Excel
    that appeared during the run is killed -- which could include the Excel
    of another session's build started in the same window. That build then
    fails safely: it was working on a temp copy, so its book is untouched.
    An Excel the estimator opened is never a candidate (it is not started
    with ``/automation -Embedding``)."""
    before = _excel_pids() if excel else set()
    kw = {} if sys.platform == "win32" else {"start_new_session": True}
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", **kw)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            out = ""
        pid = _reported_pid(out)
        targets = {pid} if pid else (_new_excels(before) if excel else set())
        for target in sorted(targets):
            _kill_pid(target)
        raise EngineTimeout(timeout, pid or (min(targets) if targets else None)) from None
    return proc.returncode, out or "", err or ""


def _tail(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines()
             if ln.strip() and not _PID_LINE.match(ln.strip())]
    return lines[-1][:300] if lines else "no output"


def _check(rc: int, out: str, err: str) -> None:
    if rc == _UNAVAILABLE_EXIT:
        raise EngineUnavailable(_tail(err or out))
    if rc != 0:
        raise RuntimeError(_tail(err or out))


# -- runners: each recalculates ``tmp`` in place or raises ------------------------------

_PY_CHILD = """import sys
from estimating_tools.calcbook.recalc import ExcelUnavailable, recalculate
try:
    recalculate(sys.argv[1], report_pid=lambda pid: print(f"EXCEL_PID={pid or 0}", flush=True))
except ExcelUnavailable as exc:
    print(exc, file=sys.stderr)
    sys.exit(%d)
""" % _UNAVAILABLE_EXIT


def _run_pywin32(tmp: Path, timeout: float) -> None:
    _check(*_spawn([sys.executable, "-c", _PY_CHILD, str(tmp)], timeout, excel=True))


_PS_SCRIPT = """$ErrorActionPreference = 'Stop'
$pidOf = $null
try {
  # Compiled before Excel starts, so the pid line follows its start at once.
  Add-Type -Namespace EstRecalc -Name Win -MemberDefinition '[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);'
  $pidOf = $true
} catch { }
try { $xl = New-Object -ComObject Excel.Application }
catch { [Console]::Error.WriteLine($_.Exception.Message); exit %(unavailable)d }
try {
  $xlpid = 0
  if ($pidOf) { try { [void][EstRecalc.Win]::GetWindowThreadProcessId([IntPtr]$xl.Hwnd, [ref]$xlpid) } catch { } }
  [Console]::Out.WriteLine("EXCEL_PID=$xlpid")
  [Console]::Out.Flush()
  $xl.Visible = $false
  $xl.DisplayAlerts = $false
  $wb = $xl.Workbooks.Open(%(path)s)
  $xl.CalculateFullRebuild()
  $wb.Save()
  $wb.Close($false)
} finally {
  $xl.Quit()
  [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
}
"""

#: PowerShell treats the curly single quotes as quote characters too.
_PS_QUOTES = "'‘’‚‛"


def _ps_literal(text: str) -> str:
    """A single-quoted PowerShell string literal of ``text``."""
    return "'" + "".join(c * 2 if c in _PS_QUOTES else c for c in text) + "'"


def _windows_path(path: Path) -> str:
    if sys.platform == "win32":
        return str(Path(path).resolve())
    done = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True,
                          timeout=30)
    if done.returncode != 0 or not done.stdout.strip():
        raise EngineUnavailable(f"wslpath could not translate {Path(path).name}: "
                                f"{_tail(done.stderr)}")
    return done.stdout.strip()


def _run_powershell(tmp: Path, timeout: float) -> None:
    exe = _powershell()
    if not exe:
        raise EngineUnavailable("powershell.exe is not reachable")
    script = _PS_SCRIPT % {"unavailable": _UNAVAILABLE_EXIT,
                           "path": _ps_literal(_windows_path(tmp))}
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    _check(*_spawn([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-EncodedCommand", encoded], timeout, excel=True))


#: Calc's "recalculate on load" for OOXML files: 0 = always (default: never).
_LO_PROFILE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
"""


def _uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    return url2pathname(unquote(parsed.path)) if os.name == "nt" else unquote(parsed.path)


def _run_soffice(tmp: Path, timeout: float) -> None:
    exe = _soffice()
    if not exe:
        raise EngineUnavailable("soffice is not on PATH")
    # ignore_cleanup_errors: a soffice killed on a timeout may still hold the
    # profile for a moment; that must not mask the timeout.
    with tempfile.TemporaryDirectory(prefix="est-recalc-", ignore_cleanup_errors=True) as work:
        work = Path(work)
        profile = work / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(_LO_PROFILE,
                                                                    encoding="utf-8")
        outdir = work / "out"
        outdir.mkdir()
        # A private profile: a running LibreOffice would otherwise swallow the
        # conversion, and this one says "recalculate on load".
        rc, out, err = _spawn([exe, f"-env:UserInstallation={profile.as_uri()}",
                               "--headless", "--norestore", "--nolockcheck", "--calc",
                               "--convert-to", "xlsx:Calc MS Excel 2007 XML",
                               "--outdir", str(outdir), str(tmp)], timeout)
        produced = outdir / tmp.name
        if rc != 0 or not produced.exists():
            raise RuntimeError(_tail(err or out))
        shutil.copyfile(produced, tmp)


_RUNNERS = {"excel-com": _run_pywin32, "excel-powershell": _run_powershell,
            "libreoffice": _run_soffice}


# -- what the copy must keep ------------------------------------------------------------

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_X14 = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"
_NS_XM = "http://schemas.microsoft.com/office/excel/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_CP = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
_MAX_ROW, _MAX_COL = 1048576, 16384
_REF = re.compile(r"^\$?([A-Z]{0,3})\$?(\d*)$")


def _q(tag: str) -> str:
    return f"{{{_NS}}}{tag}"


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(_q("t")))


def _cell_value(root, ref: str, strings: list):
    for c in root.iter(_q("c")):
        if c.get("r") != ref:
            continue
        kind, v = c.get("t"), c.find(_q("v"))
        if kind == "s" and v is not None:
            return strings[int(v.text)]
        if kind == "inlineStr":
            node = c.find(_q("is"))
            return _text(node) if node is not None else ""
        return v.text if v is not None else None
    return None


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _col_letters(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _end(ref: str, low: bool):
    m = _REF.match(ref.upper())
    if not m or not (m.group(1) or m.group(2)):
        raise ValueError(f"bad reference {ref!r}")
    col = _col_index(m.group(1)) if m.group(1) else (1 if low else _MAX_COL)
    row = int(m.group(2)) if m.group(2) else (1 if low else _MAX_ROW)
    return row, col


def _rects(sqref: str) -> list:
    """``"A1 B2:C5 D:D"`` -> ``[(r1, c1, r2, c2), ...]``."""
    out = []
    for part in (sqref or "").split():
        a, _, b = part.partition(":")
        r1, c1 = _end(a, True)
        r2, c2 = _end(b, False) if b else (r1, c1)
        out.append((min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)))
    return out


def _validations(root) -> list:
    """``[(type, rect), ...]`` over both the main and the x14 namespace."""
    found = []
    for dv in root.iter(_q("dataValidation")):
        found += [(dv.get("type") or "none", r) for r in _rects(dv.get("sqref"))]
    for dv in root.iter(f"{{{_NS_X14}}}dataValidation"):
        sq = dv.find(f"{{{_NS_XM}}}sqref")
        found += [(dv.get("type") or "none", r) for r in _rects(sq.text if sq is not None else "")]
    return found


def _covered(rect, others) -> bool:
    """Is ``rect`` inside the union of ``others``? Exact cell by cell for a
    range of up to 200,000 cells (Excel may merge or split ranges); a larger
    range must sit inside a single one of ``others``."""
    r1, c1, r2, c2 = rect
    if any(o[0] <= r1 and o[1] <= c1 and o[2] >= r2 and o[3] >= c2 for o in others):
        return True
    if (r2 - r1 + 1) * (c2 - c1 + 1) > 200_000:
        return False
    near = [o for o in others if not (o[2] < r1 or o[0] > r2 or o[3] < c1 or o[1] > c2)]
    return all(any(o[0] <= r <= o[2] and o[1] <= c <= o[3] for o in near)
               for r in range(r1, r2 + 1) for c in range(c1, c2 + 1))


def _rect_ref(rect) -> str:
    r1, c1, r2, c2 = rect
    a, b = f"{_col_letters(c1)}{r1}", f"{_col_letters(c2)}{r2}"
    return a if a == b else f"{a}:{b}"


def _target(text) -> str:
    """A defined name's target, normalised for comparison: Excel may drop or
    add the ``$`` anchors and the quotes around a sheet name."""
    return "".join((text or "").split()).replace("$", "").replace("'", "").upper()


def _fingerprint(path: Path) -> dict:
    """What a calculating pass must not lose, read from the package XML."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        props = {}
        if "docProps/custom.xml" in names:
            for p in ET.fromstring(z.read("docProps/custom.xml")).iter(f"{{{_NS_CP}}}property"):
                props[p.get("name")] = "".join(c.text or "" for c in p)
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        defined = {(d.get("name"), d.get("localSheetId")): _target(d.text)
                   for d in wb.iter(_q("definedName"))}
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{{{_NS_REL}}}Relationship")}
        strings = []
        if "xl/sharedStrings.xml" in names:
            strings = [_text(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))
                       .iter(_q("si"))]
        sheets = {}
        for s in wb.iter(_q("sheet")):
            title, state = s.get("name"), s.get("state") or "visible"
            target = targets[s.get(f"{{{_NS_R}}}id")]
            part = target.lstrip("/") if target.startswith("/") else "xl/" + target
            root = ET.fromstring(z.read(part))
            cols, outline = set(), set()
            for col in root.iter(_q("col")):
                span = range(int(col.get("min")), int(col.get("max")) + 1)
                if col.get("hidden") in ("1", "true"):
                    cols.update(span)
                level = int(col.get("outlineLevel") or 0)
                if level:
                    outline.update(("column", i, level) for i in span)
            for row in root.iter(_q("row")):
                level = int(row.get("outlineLevel") or 0)
                if level:
                    outline.add(("row", int(row.get("r")), level))
            sheets[title] = {
                "state": state,
                "validations": _validations(root),
                "hidden_cols": cols,
                "outline": outline,
                "a1": (_cell_value(root, "A1", strings) if state != "visible" else None),
            }
    return {"props": props, "names": defined, "sheets": sheets}


def _lost(before: dict, after: dict) -> list:
    """What ``after`` dropped or changed of ``before``; empty when it kept all."""
    lost = []
    for key, value in before["props"].items():
        if after["props"].get(key) != value:
            lost.append(f"custom property {key!r}")
    for key, target in sorted(before["names"].items(), key=str):
        if key not in after["names"]:
            lost.append(f"defined name {key[0]!r}")
        elif after["names"][key] != target:
            # HeavyBook's patch finds its prototype rows through these targets.
            lost.append(f"defined name {key[0]!r} target {target} (now {after['names'][key]})")
    for title, was in before["sheets"].items():
        now = after["sheets"].get(title)
        if now is None:
            lost.append(f"sheet {title!r}")
            continue
        if now["state"] != was["state"]:
            lost.append(f"sheet {title!r} state {was['state']} (now {now['state']})")
        if was["a1"] != now["a1"]:
            lost.append(f"{title}!A1 stamp")
        by_type: dict = {}
        for kind, rect in now["validations"]:
            by_type.setdefault(kind, []).append(rect)
        for kind, rect in was["validations"]:
            if not _covered(rect, by_type.get(kind, [])):
                lost.append(f"data validation ({kind}) on {title}!{_rect_ref(rect)}")
        for i in sorted(was["hidden_cols"] - now["hidden_cols"]):
            lost.append(f"hidden column {title}!{_col_letters(i)}")
        if was["outline"] - now["outline"]:
            lost.append(f"outline levels on {title!r}")
    return lost


def _keep_full_calc(path: Path) -> None:
    from estimating_tools.exchange.writer import write
    write(path, full_calc_on_load=True)


# -- the pass ---------------------------------------------------------------------------

def _families(engine: str, auto_order) -> list:
    families = list(auto_order) if engine == "auto" else [engine]
    for family in families:
        if family not in _FAMILIES:
            raise ValueError(f"unknown recalc engine {family!r}; one of {', '.join(CHOICES)}")
    return families


def _remove(*paths: Path, wait: float = 5.0) -> None:
    """Delete ``paths``, retrying while a just-killed Excel lets go of them."""
    deadline = time.monotonic() + wait
    for p in paths:
        while True:
            try:
                p.unlink(missing_ok=True)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.2)


#: A Windows, UNC or POSIX path ending in a workbook name (group 1).
_WORKBOOK_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|/)(?:[^'\"<>|*?\r\n]*[\\/])?"
                            r"([^\\/'\"<>|*?\r\n]+?\.xlsx)")


def _short(message: str, directory: Path) -> str:
    """``message`` with the book's folder cut away, so a failure names files
    and never prints a full path."""
    forms = {str(directory), str(Path(directory).resolve())}
    for form in list(forms):
        forms |= {form.replace("/", "\\"), form.replace("\\", "/")}
    for form in sorted(forms, key=len, reverse=True):
        base = form.rstrip("\\/")
        message = message.replace(base + "\\", "").replace(base + "/", "")
    return _WORKBOOK_PATH.sub(r"\1", message)


def _attempt(name: str, path: Path, before: dict, timeout: float) -> None:
    """Recalculate a copy of ``path`` with engine ``name`` and swap it in, or
    raise with the book untouched."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.recalc-", suffix=".xlsx")
    os.close(fd)
    tmp = Path(tmp)
    try:
        shutil.copy2(path, tmp)
        _RUNNERS[name](tmp, timeout)
        try:
            after = _fingerprint(tmp)
        except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, OSError) as exc:
            raise RuntimeError(f"wrote an unreadable workbook ({exc})") from exc
        lost = _lost(before, after)
        if lost:
            raise RuntimeError("dropped " + ", ".join(lost))
        _keep_full_calc(tmp)
        try:
            os.replace(tmp, path)
        except OSError as exc:
            raise RuntimeError(f"could not replace {path.name} (open in Excel, or "
                               f"read-only?): {exc.strerror or exc}") from exc
    finally:
        # The copy and Excel's owner file for it, should either outlive a kill.
        _remove(tmp, tmp.parent / ("~$" + tmp.name))


def recalculate(path, *, engine: str = "auto", auto_order=AUTO_ORDER,
                timeout: float = DEFAULT_TIMEOUT) -> RecalcResult:
    """Store cached formula values in the workbook at ``path``.

    ``engine``: ``auto`` (the families of ``auto_order``, Excel by default),
    ``excel``, ``libreoffice`` or ``off``. Within a family the next engine
    runs only when the previous one could not start. Raises ValueError only
    for an unknown engine name."""
    if engine not in CHOICES:
        raise ValueError(f"unknown recalc engine {engine!r}; one of {', '.join(CHOICES)}")
    families = _families(engine, auto_order) if engine != "off" else []
    if (os.environ.get(ENV_VAR) or "").strip().lower() == "off":
        return RecalcResult(None, f"off ({ENV_VAR}=off)")
    if engine == "off":
        return RecalcResult(None, "off (--recalc off)")
    path = Path(path)
    if not path.is_file():
        return RecalcResult(None, f"no such file: {path.name}")
    plan = [[n for n in _FAMILIES[f] if _available(n)] for f in families]
    if not any(plan):
        wanted = " or ".join(_LABEL[n] for f in families for n in _FAMILIES[f])
        return RecalcResult(None, f"no calculating engine found ({wanted})")
    try:
        before = _fingerprint(path)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, OSError) as exc:
        return RecalcResult(None, f"cannot read {path.name} as a workbook ({exc})")
    failures = []
    for engines in plan:
        for name in engines:
            try:
                _attempt(name, path, before, timeout)
            except EngineUnavailable as exc:
                failures.append(f"{_LABEL[name]} could not start: {_short(str(exc), path.parent)}")
                continue
            except EngineTimeout as exc:
                killed = f" (Excel process {exc.pid} ended)" if exc.pid else ""
                failures.append(f"{_LABEL[name]} timed out after {timeout:g}s{killed}")
            except Exception as exc:  # noqa: BLE001 -- any engine failure is a reason
                failures.append(f"{_LABEL[name]} failed: {_short(str(exc), path.parent)}")
            else:
                return RecalcResult(name, _LABEL[name])
            break  # it ran and failed: the family's other engine would meet the same
    return RecalcResult(None, "; ".join(failures) + "; the book is as written")
