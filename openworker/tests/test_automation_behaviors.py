"""Behavioral coverage for the seeded automations: (a) every payload's
instructions reference only skills that exist in the ported tree, and (b)
the deterministic core the sweep leans on (the quote-space coverage board)
actually produces a board from fixtures."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PAYLOADS = sorted((HERE / "automations" / "payloads").glob("*.json"))
SKILLS = {p.name for p in (HERE / "skills").iterdir() if p.is_dir()}


def test_payload_skill_references_exist():
    missing = []
    matches_by_payload = {}
    for path in PAYLOADS:
        instructions = json.loads(path.read_text(encoding="utf-8"))["instructions"]
        found = re.findall(r"`([a-z0-9-]+)` skill", instructions)
        matches_by_payload[path.name] = found
        for name in found:
            if name not in SKILLS:
                missing.append(f"{path.name}: {name}")
    assert not missing, f"payloads reference unported skills: {missing}"
    # Guard against the phrasing-dependent regex going vacuous: the sweep
    # payload is known to name its skills in `backtick` skill form.
    assert matches_by_payload.get("bid-day-quote-sweep.json"), \
        "regex matched nothing in bid-day-quote-sweep.json — phrasing drifted?"


def test_sweep_references_coverage_and_compare():
    text = json.loads((HERE / "automations" / "payloads" /
                       "bid-day-quote-sweep.json").read_text(encoding="utf-8"))
    assert "quote-coverage" in text["instructions"]
    assert "compare-quotes" in text["instructions"]


def test_coverage_core_builds_a_board(tmp_path, capsys):
    from estimating_tools.quotespace import cli
    journal = tmp_path / "solicitations.jsonl"
    assert cli.main(["solicit", "--journal", str(journal),
                     "--package", "Guardrail", "--vendor", "Roadside Inc",
                     "--status", "sent", "--sent-at", "2026-08-07"]) == 0
    packages = tmp_path / "packages.json"
    packages.write_text(json.dumps([
        {"name": "Guardrail", "strategy": "sub_out",
         "items": [{"schedule": "A", "item_number": "40",
                    "description": "MGS"}]}]), encoding="utf-8")
    assert cli.main(["coverage", "--journal", str(journal),
                     "--packages", str(packages)]) == 0
    assert "Guardrail" in capsys.readouterr().out
