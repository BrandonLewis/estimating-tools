from __future__ import annotations

import json
import os
from pathlib import Path

from estimating_tools.estimate_spec.tests._snapshot import snapshot
from estimating_tools.heavycivil import build, style

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "heavycivil.snapshot.json"


def test_golden_snapshot(book):
    # Round-trip through JSON so int keys (row heights) compare as the
    # golden file stores them: as strings.
    snap = json.loads(json.dumps(snapshot(book), sort_keys=True))
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
