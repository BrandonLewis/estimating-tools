"""#256: consumer-registered pre-render config checks.

A consumer can require a fixed set of cost blocks (a missing block silently
books $0), but that policy lives in the consumer's repo while `est-estimate
build` runs the wheel's build.py. These tests pin the hook: checks are
discovered via an entry-point group, findings go to stderr, and a check never
blocks the build (nor propagates its own error). `--no-lint` skips them.
"""
from __future__ import annotations

from pathlib import Path

from estimating_tools.estimate_spec import build as build_mod
from estimating_tools.estimate_spec import format_pack as fp

SPEC_DIR = Path(__file__).resolve().parents[1]
LEGACY_DIR = SPEC_DIR / "tests" / "fixtures" / "packs" / "legacy_demo"
EXAMPLE = LEGACY_DIR / "examples" / "demo-pipeline.estimate.yaml"


class _FakeEP:
    """Stand-in for an importlib.metadata EntryPoint (name + load())."""
    def __init__(self, name, fn):
        self.name = name
        self._fn = fn

    def load(self):
        return self._fn


def _patch_eps(monkeypatch, eps):
    monkeypatch.setattr(build_mod, "entry_points", lambda group=None: eps)


def test_no_registered_checks_returns_empty(monkeypatch):
    _patch_eps(monkeypatch, [])
    assert build_mod.run_config_checks({"items": []}) == []


def test_findings_are_prefixed_with_check_name(monkeypatch):
    _patch_eps(monkeypatch, [_FakeEP("cost-blocks", lambda cfg: ["missing FUEL block"])])
    assert build_mod.run_config_checks({"items": []}) == ["cost-blocks: missing FUEL block"]


def test_a_check_that_raises_is_caught_not_propagated(monkeypatch):
    def boom(cfg):
        raise RuntimeError("kaboom")
    _patch_eps(monkeypatch, [_FakeEP("bad", boom)])
    out = build_mod.run_config_checks({"items": []})
    assert len(out) == 1 and "bad" in out[0] and "kaboom" in out[0]


def test_build_runs_checks_to_stderr_and_still_writes(monkeypatch, tmp_path, capsys):
    # A finding must NOT abort the render — it is advisory only.
    monkeypatch.setattr(build_mod, "run_config_checks", lambda cfg: ["missing FUEL block"])
    out = tmp_path / "out.xlsx"
    result = build_mod.build(str(EXAMPLE), str(out), pack=fp.load_pack(LEGACY_DIR))
    assert Path(result).exists()
    assert "missing FUEL block" in capsys.readouterr().err


def test_build_lint_false_skips_checks(monkeypatch, tmp_path, capsys):
    called = []
    monkeypatch.setattr(build_mod, "run_config_checks", lambda cfg: called.append(1) or [])
    out = tmp_path / "out.xlsx"
    build_mod.build(str(EXAMPLE), str(out), pack=fp.load_pack(LEGACY_DIR), lint=False)
    assert called == []
    assert capsys.readouterr().err == ""


def test_cli_no_lint_flag_disables_checks(monkeypatch, tmp_path):
    from estimating_tools.estimate_spec import cli
    seen = {}
    monkeypatch.setattr(build_mod, "build",
                        lambda config, output, pack=None, stamp=True, lint=True: seen.update(lint=lint) or str(output))
    out = tmp_path / "o.xlsx"
    assert cli.main(["build", str(EXAMPLE), "-o", str(out), "--format", str(LEGACY_DIR), "--no-lint"]) == 0
    assert seen["lint"] is False
    assert cli.main(["build", str(EXAMPLE), "-o", str(out), "--format", str(LEGACY_DIR)]) == 0
    assert seen["lint"] is True
