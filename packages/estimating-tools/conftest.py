"""Suite-wide: no test starts Excel or LibreOffice (#370).

The calculating pass is opt-in (``--recalc excel``; the default is off), but
a test may ask for it. ``ESTIMATING_RECALC=off`` switches every engine off
whatever was asked, so a build under test
writes exactly the bytes the writer produced -- the HeavyBook golden and
determinism tests depend on that -- and never shells out. Set at import time
so subprocesses a test starts inherit it too. Tests of the helper itself lift
it with ``monkeypatch.delenv``.

Lives beside the package, not inside it, so it never ships in the wheel.
"""
import os

os.environ["ESTIMATING_RECALC"] = "off"
