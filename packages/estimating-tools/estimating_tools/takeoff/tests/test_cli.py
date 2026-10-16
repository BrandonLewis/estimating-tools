import json

from estimating_tools.takeoff.cli import main


def test_plan_subcommand_default_target_is_estimate_structures(tmp_path, capsys):
    takeoff = {
        "organization_id": 7,
        "project_ref": "RT-12",
        "rows": [{"description": "Deck", "kind": "quantity", "quantity": 250,
                  "unit": "CY", "item_number": "0400", "schedule": "A",
                  "elements": [{"name": "S-DECK-1", "section_type": "decks",
                                "count": 1, "length_ft": 120.0, "width_ft": 45.0,
                                "height_ft": 1.5}]}],
    }
    tk = tmp_path / "takeoff.json"; tk.write_text(json.dumps(takeoff))

    rc = main(["plan", str(tk), "--structure-id", "BR-9"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "quantity_updates" not in out and "quantity_creates" not in out
    sp = out["structure_plans"][0]
    assert sp["structure_id"] == "BR-9"
    assert sp["sections"][0]["dimensions"] == {"length": 120.0, "width": 45.0,
                                               "height": 1.5}
    assert out["advisory_quantity_check"] == [
        {"item_number": "0400", "schedule": "A", "model_qty": 250, "unit": "CY"}]


def test_plan_subcommand_legacy_target_emits_update_and_warning(tmp_path, capsys):
    takeoff = {
        "organization_id": 7,
        "rows": [{"description": "Formwork", "kind": "quantity", "quantity": 500,
                  "unit": "SF", "item_number": "0301", "schedule": "A"}],
    }
    existing = [{"item_number": "0301", "schedule": "A", "project_bid_item_id": 55}]
    tk = tmp_path / "takeoff.json"; tk.write_text(json.dumps(takeoff))
    ex = tmp_path / "existing.json"; ex.write_text(json.dumps(existing))

    rc = main(["plan", str(tk), "--target", "bid-item-quantities",
               "--existing", str(ex)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["quantity_updates"][0]["estimated_quantity"] == 500
    assert out["quantity_updates"][0]["project_bid_item_id"] == 55
    assert out["WARNING"] == ("writes OFFICIAL agency schedule quantities — "
                              "forbidden on live bids; see BM #984")


def test_plan_subcommand_structures_without_structure_id_errors(tmp_path, capsys):
    takeoff = {"organization_id": 7,
               "rows": [{"description": "Deck", "kind": "quantity", "quantity": 1,
                         "item_number": "0400"}]}
    tk = tmp_path / "takeoff.json"; tk.write_text(json.dumps(takeoff))
    rc = main(["plan", str(tk)])  # no --structure-id, no project_ref
    assert rc == 1
    assert "structure" in capsys.readouterr().err


def test_plan_subcommand_bad_file_returns_1(tmp_path, capsys):
    rc = main(["plan", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_plan_subcommand_non_object_takeoff_returns_1(tmp_path, capsys):
    # valid JSON but not an object -> clean error, not a traceback
    tk = tmp_path / "takeoff.json"; tk.write_text("[]")
    rc = main(["plan", str(tk)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_plan_subcommand_malformed_existing_returns_1(tmp_path, capsys):
    # --existing is valid JSON but a wrong shape (object, not a list of dicts)
    takeoff = {"organization_id": 7,
               "rows": [{"description": "x", "kind": "quantity", "quantity": 1,
                         "item_number": "0001"}]}
    tk = tmp_path / "takeoff.json"; tk.write_text(json.dumps(takeoff))
    ex = tmp_path / "existing.json"; ex.write_text('{"not": "a list"}')
    rc = main(["plan", str(tk), "--existing", str(ex)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_plan_subcommand_existing_list_of_non_dicts_returns_1(tmp_path, capsys):
    # --existing is a JSON list but its elements aren't objects
    takeoff = {"organization_id": 7,
               "rows": [{"description": "x", "kind": "quantity", "quantity": 1,
                         "item_number": "0001"}]}
    tk = tmp_path / "takeoff.json"; tk.write_text(json.dumps(takeoff))
    ex = tmp_path / "existing.json"; ex.write_text('["not-a-dict"]')
    rc = main(["plan", str(tk), "--existing", str(ex)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
