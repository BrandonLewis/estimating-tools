"""The Phase-2 estimating_tools.bim/.sheets shims were REMOVED in Phase 3c.

This is the inverse of the Phase-2 pin that lived here: the old import paths
must now fail loudly (a stale editable install silently resurrecting them is
the failure mode), while the real bimforge packages import fine.
"""
import importlib.util

import pytest


@pytest.mark.parametrize("gone", ["estimating_tools.bim",
                                  "estimating_tools.sheets"])
def test_shim_import_paths_are_gone(gone):
    assert importlib.util.find_spec(gone) is None, (
        f"{gone} is importable — the Phase-2 shim is back (stale editable "
        f"install? reinstall estimating_tools) or was re-added")


@pytest.mark.parametrize("real", ["bimforge.bim", "bimforge.sheets"])
def test_the_real_packages_still_import(real):
    importlib.import_module(real)
