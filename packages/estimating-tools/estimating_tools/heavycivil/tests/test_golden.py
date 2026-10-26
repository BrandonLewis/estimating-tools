from __future__ import annotations

import json
import os
from pathlib import Path

from estimating_tools.estimate_spec.tests._snapshot import snapshot
from estimating_tools.heavycivil import build, style

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "heavycivil.snapshot.json"


def _mask_baseline(snap):
    """The baseline chunks are zlib output, which differs between zlib
    builds (CPython on Windows ships zlib-ng): pin that they are there, not
    their bytes. The layout JSON's checksum of the decoded payload stays."""
    for addr, cell in snap["sheets"]["_wb"]["cells"].items():
        if addr.startswith("B"):
            cell["v"] = "<baseline>"
    return snap


def test_golden_snapshot(book):
    # Round-trip through JSON so int keys (row heights) compare as the
    # golden file stores them: as strings.
    snap = _mask_baseline(json.loads(json.dumps(snapshot(book), sort_keys=True)))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert snap == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_rebuild_is_byte_identical(doc, tmp_path):
    paths = []
    for name in ("a.xlsx", "b.xlsx"):
        wb = build.build(doc, style=style.load_style(), exported_at="2026-10-20T09:00:00Z",
                         host="www.bidsheet.ai")
        build.save(wb, tmp_path / name)
        paths.append(tmp_path / name)
    assert paths[0].read_bytes() == paths[1].read_bytes()
