import json
import warnings

import pytest
import yaml

from estimating_tools.profiles.cli import main
from estimating_tools.profiles.loader import load_one


def test_cli_writes_profile_dir(tmp_path):
    target = tmp_path / "acme-profile"
    rc = main([str(target), "--name", "Acme Builders"])
    assert rc == 0
    assert (target / "profile.yaml").exists()
    assert (target / "tree.yaml").exists() and (target / "letterhead.md").exists()
    prof = yaml.safe_load((target / "profile.yaml").read_text())
    assert prof["name"] == "Acme Builders" and prof["kind"] == "org"


def test_cli_applies_fields(tmp_path):
    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps({"company_name": "Acme, Inc.", "compliance_label": "DBE"}))
    target = tmp_path / "p"
    rc = main([str(target), "--name", "Acme", "--fields", str(fields)])
    assert rc == 0
    prof = yaml.safe_load((target / "profile.yaml").read_text())
    assert prof["letterhead"]["company_name"] == "Acme, Inc."
    assert prof["argot"]["compliance_label"] == "DBE"


def test_cli_missing_name_exits(tmp_path):
    with pytest.raises(SystemExit):           # argparse: --name is required
        main([str(tmp_path / "p")])


def test_cli_schema_violation_exits_nonzero(tmp_path, capsys):
    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps({"naming": ["not", "a", "dict"]}))
    rc = main([str(tmp_path / "p"), "--name", "A", "--fields", str(fields)])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()


def test_cli_bad_fields_json_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json ")
    rc = main([str(tmp_path / "p"), "--name", "A", "--fields", str(bad)])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()


def test_cli_non_object_fields_json_exits_nonzero(tmp_path, capsys):
    # valid JSON but not an object (a list) -> clean return 1, not an AttributeError crash
    bad = tmp_path / "list.json"
    bad.write_text('["not", "an", "object"]')
    rc = main([str(tmp_path / "p"), "--name", "A", "--fields", str(bad)])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()


def test_cli_output_round_trips_through_loader(tmp_path):
    target = tmp_path / "p"
    assert main([str(target), "--name", "Acme Builders"]) == 0
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        sections = load_one(target)
    assert sections["folder_conventions"]["tree"] == str((target / "tree.yaml").resolve())
