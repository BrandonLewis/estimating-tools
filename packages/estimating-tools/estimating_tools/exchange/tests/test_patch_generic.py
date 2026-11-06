"""The patch is the engine's (``exchange.patch``): HeavyBook delegates to it,
and its own package is gone."""
from __future__ import annotations

import importlib.util

from estimating_tools.heavybook import pack as hb_pack


def test_heavybook_patches_through_the_generic_patch(monkeypatch, tmp_path):
    from estimating_tools.exchange import patch as ex_patch

    calls = []

    def fake(book, change_set, result, payload, *, pack):
        calls.append(pack)
        return "report"

    monkeypatch.setattr(ex_patch, "patch", fake)
    p = hb_pack.pack()
    assert p.patch(tmp_path / "b.xlsx", object(), object(), {}) == "report"
    assert calls == [p]


def test_the_heavybook_patch_package_is_gone():
    assert importlib.util.find_spec("estimating_tools.heavybook.patch") is None
