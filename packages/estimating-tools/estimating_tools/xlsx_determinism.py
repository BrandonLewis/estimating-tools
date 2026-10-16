"""Byte-deterministic .xlsx output.

openpyxl stamps the current time into `docProps/core.xml` and into every zip
member's header, so two runs over identical data produce different bytes. That
defeats any diff-based regression check. Pinning both to a fixed stamp makes a
rebuild byte-identical whenever the content is.

Pair `BUILD_STAMP` (set on `wb.properties.created`/`.modified` before saving)
with `normalize_xlsx(path)` (called after saving).
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

#: Fixed build time. Its value is arbitrary; only its constancy matters.
BUILD_STAMP = datetime(2026, 8, 16, 12, 0, 0)


def normalize_xlsx(path) -> None:
    """Rewrite the .xlsx at `path` with every timestamp pinned to BUILD_STAMP."""
    stamp = BUILD_STAMP.timetuple()[:6]
    iso = BUILD_STAMP.strftime('%Y-%m-%dT%H:%M:%SZ').encode()
    with zipfile.ZipFile(path) as zin:
        entries = [(i.filename, zin.read(i.filename)) for i in zin.infolist()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries:
            if name == 'docProps/core.xml':
                data = re.sub(rb'(<dcterms:modified[^>]*>)[^<]*',
                              rb'\g<1>' + iso, data)
            zi = zipfile.ZipInfo(name, date_time=stamp)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, data)
    Path(path).write_bytes(buf.getvalue())
