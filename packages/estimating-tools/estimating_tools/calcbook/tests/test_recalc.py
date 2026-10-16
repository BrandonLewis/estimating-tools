"""Tests for the --recalc COM helper (#202).

The COM path itself needs Excel (Windows-only, not on CI), so we only assert
the guard: a clean error when pywin32 is unavailable, and that the helper uses
DispatchEx (never Dispatch, which would attach to the estimator's open Excel).
"""
from __future__ import annotations

import sys
import types

import pytest

from estimating_tools.calcbook import recalc


def test_recalculate_without_pywin32_is_a_clean_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32com", None)
    monkeypatch.setitem(sys.modules, "win32com.client", None)
    with pytest.raises(RuntimeError, match="pywin32|Excel|Windows"):
        recalc.recalculate("nope.xlsx")


def test_recalculate_converts_com_error_to_clean_error(monkeypatch, tmp_path):
    # pywin32 present but Excel not registered: DispatchEx raises a COM error,
    # which must surface as the promised RuntimeError, not a raw COM exception.
    def boom(*a):
        raise OSError("Class not registered")

    fake_client = types.SimpleNamespace(DispatchEx=boom, Dispatch=boom)
    monkeypatch.setitem(sys.modules, "win32com",
                        types.SimpleNamespace(client=fake_client))
    monkeypatch.setitem(sys.modules, "win32com.client", fake_client)
    with pytest.raises(RuntimeError, match="Excel"):
        recalc.recalculate(str(tmp_path / "b.xlsx"))


def test_recalculate_uses_dispatchex(monkeypatch, tmp_path):
    calls = {}

    class FakeApp:
        Visible = True
        DisplayAlerts = True

        class _WBs:
            def Open(self, path):
                calls["opened"] = path
                app = FakeApp()

                class _WB:
                    Application = app

                    def Save(self):
                        calls["saved"] = True

                    def Close(self, SaveChanges=True):
                        calls["closed"] = True
                app.CalculateFullRebuild = lambda: calls.__setitem__("recalc", True)
                return _WB()
        Workbooks = _WBs()

        def CalculateFullRebuild(self):
            calls["recalc"] = True

        def Quit(self):
            calls["quit"] = True

    fake_client = types.SimpleNamespace(
        Dispatch=lambda *a: calls.__setitem__("used_dispatch", True) or FakeApp(),
        DispatchEx=lambda *a: calls.__setitem__("used_dispatchex", True) or FakeApp(),
    )
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=fake_client))
    monkeypatch.setitem(sys.modules, "win32com.client", fake_client)

    f = tmp_path / "b.xlsx"
    f.write_text("x")
    recalc.recalculate(str(f))
    assert calls.get("used_dispatchex") is True
    assert "used_dispatch" not in calls
    assert calls.get("quit") is True
