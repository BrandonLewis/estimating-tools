"""The package is ``heavybook``. ``heavycivil`` was a one-release import
shim (0.1.96); it is gone. Books stamped ``heavycivil 1`` still read."""
from __future__ import annotations

import importlib

import pytest


def test_heavybook_is_the_package():
    import estimating_tools.heavybook as hb
    assert hb.FORMAT_NAME == "heavybook"
    assert "heavycivil" in hb.ACCEPTED_FORMATS and "heavybook" in hb.ACCEPTED_FORMATS


def test_the_heavycivil_import_shim_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("estimating_tools.heavycivil")
