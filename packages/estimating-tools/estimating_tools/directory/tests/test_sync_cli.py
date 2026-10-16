"""dir-sync CLI (estimating_tools.directory.sync_cli)."""
import json

from estimating_tools.directory.sync_cli import main


def _write(tmp_path, name, orgs):
    p = tmp_path / name
    p.write_text(json.dumps({"organizations": orgs}), encoding="utf-8")
    return p


def test_plan_markdown_and_json(tmp_path, capsys):
    local = _write(tmp_path, "local.json",
                   [{"name": "Local Only LLC", "contacts": []}])
    remote = _write(tmp_path, "remote.json", [])
    assert main(["plan", str(local), str(remote)]) == 0
    out = capsys.readouterr().out
    assert "# Directory Sync Plan" in out and "Local Only LLC" in out

    assert main(["plan", str(local), str(remote), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["creates"][0]["org"] == "Local Only LLC"


def test_plan_missing_file(tmp_path, capsys):
    rc = main(["plan", str(tmp_path / "nope.json"), str(tmp_path / "n2.json")])
    assert rc == 1
    assert "no such file" in capsys.readouterr().err
