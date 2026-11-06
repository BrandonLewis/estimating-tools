from __future__ import annotations

from dataclasses import dataclass

import pytest

from estimating_tools.exchange import registry
from estimating_tools.exchange.types import BookFacts


@dataclass
class _Pack:
    name: str
    verdict: str
    version: str = "1"
    contract: str = "1"

    def detect(self, facts):
        return self.verdict


def _install(monkeypatch, *packs):
    monkeypatch.setattr(registry, "discover", lambda: registry.Discovery(list(packs), []))


def test_packs_lists_registered_packs_sorted_by_name(monkeypatch):
    _eps(monkeypatch, _EP("z", lambda: _Pack("zeta", "none")),
         _EP("a", lambda: _Pack("alpha", "none")))
    assert [p.name for p in registry.packs()] == ["alpha", "zeta"]


def test_pack_for_returns_the_one_that_says_ok(monkeypatch):
    _install(monkeypatch, _Pack("a", "none"), _Pack("b", "ok"))
    assert registry.pack_for(BookFacts(path="x")).name == "b"


def test_pack_for_refuses_two_claimants(monkeypatch):
    _install(monkeypatch, _Pack("a", "ok"), _Pack("b", "ok"))
    with pytest.raises(LookupError, match="a, b"):
        registry.pack_for(BookFacts(path="x"))


def test_pack_for_reports_newer_and_bad_before_none(monkeypatch):
    _install(monkeypatch, _Pack("a", "newer"), _Pack("b", "none"))
    with pytest.raises(LookupError, match="newer"):
        registry.pack_for(BookFacts(path="x"))
    _install(monkeypatch, _Pack("a", "bad"))
    with pytest.raises(LookupError, match="damaged"):
        registry.pack_for(BookFacts(path="x"))


def test_pack_for_with_no_claimant(monkeypatch):
    _install(monkeypatch, _Pack("a", "none"))
    with pytest.raises(LookupError, match="no installed pack"):
        registry.pack_for(BookFacts(path="x"))


class _EP:
    def __init__(self, name, factory, value="mod:fn"):
        self.name, self.value, self._factory = name, value, factory

    def load(self):
        if isinstance(self._factory, Exception):
            raise self._factory
        return self._factory


def _eps(monkeypatch, *eps):
    monkeypatch.setattr(registry, "_entry_points", lambda: list(eps))


def test_a_broken_entry_point_is_reported_and_the_rest_still_work(monkeypatch):
    bad = _EP("bad", ImportError("boom"), "bad.mod:make")
    _eps(monkeypatch, bad, _EP("good", lambda: _Pack("good", "ok")))
    found = registry.discover()
    assert [p.name for p in found.packs] == ["good"]
    assert len(found.problems) == 1 and "bad.mod:make" in found.problems[0]
    assert registry.pack_for(BookFacts(path="x")).name == "good"
    _eps(monkeypatch, bad, _EP("good", lambda: _Pack("good", "none")))
    with pytest.raises(LookupError, match="problems: .*bad.mod:make"):
        registry.pack_for(BookFacts(path="x"))


def test_a_detect_that_raises_is_recorded_and_others_still_win(monkeypatch):
    class Raises(_Pack):
        def detect(self, facts):
            raise RuntimeError("kaput")

    _eps(monkeypatch, _EP("r", lambda: Raises("r", "none")),
         _EP("g", lambda: _Pack("g", "ok")))
    assert registry.pack_for(BookFacts(path="x")).name == "g"
    _eps(monkeypatch, _EP("r", lambda: Raises("r", "none")))
    with pytest.raises(LookupError, match="r: detect failed: kaput"):
        registry.pack_for(BookFacts(path="x"))


def test_an_unknown_verdict_is_treated_as_none_and_recorded(monkeypatch):
    _eps(monkeypatch, _EP("a", lambda: _Pack("a", "OK")))
    with pytest.raises(LookupError, match="no installed pack.*unknown verdict 'OK'"):
        registry.pack_for(BookFacts(path="x"))


def test_an_unhashable_verdict_is_recorded_and_others_still_win(monkeypatch):
    _eps(monkeypatch, _EP("d", lambda: _Pack("d", {})), _EP("g", lambda: _Pack("g", "ok")))
    assert registry.pack_for(BookFacts(path="x")).name == "g"
    _eps(monkeypatch, _EP("d", lambda: _Pack("d", {})))
    with pytest.raises(LookupError, match="no installed pack.*d returned an unknown verdict"):
        registry.pack_for(BookFacts(path="x"))


def test_two_packs_with_one_name_keep_the_first(monkeypatch):
    _eps(monkeypatch, _EP("a", lambda: _Pack("same", "none"), "m1:f"),
         _EP("b", lambda: _Pack("same", "none"), "m2:f"))
    found = registry.discover()
    assert len(found.packs) == 1
    assert len(found.problems) == 1
    assert "m1:f" in found.problems[0] and "m2:f" in found.problems[0]


def test_the_real_entry_points_load_heavybook_and_fieldbook():
    names = {p.name for p in registry.packs()}
    assert {"heavybook", "fieldbook"} <= names


def test_a_pack_without_a_name_is_reported_and_discovery_continues(monkeypatch):
    class _Seven:
        name = 7

    _eps(monkeypatch, _EP("bad", lambda: object(), "m:f"),
         _EP("seven", lambda: _Seven(), "m:g"),
         _EP("ok", lambda: _Pack("alpha", "none")))
    found = registry.discover()
    assert [p.name for p in found.packs] == ["alpha"]
    assert found.problems == ["pack bad (m:f) has no name; ignored",
                              "pack seven (m:g) has no name; ignored"]
