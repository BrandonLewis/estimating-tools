import json

from estimating_tools.estimate_spec.bm_sync.sidecar import QuoteSync, Sidecar, choice_of, file_sha


def test_missing_sidecar_is_empty(tmp_path):
    sc = Sidecar.load(tmp_path / "bm-sync.json")
    assert sc.project_id is None and sc.package("Reinforcing steel").quotes == {}


def test_round_trip_keeps_every_field(tmp_path):
    sc = Sidecar.load(tmp_path / "bm-sync.json"); sc.project_id = 1234; sc.estimate_id = 100
    p = sc.package("Reinforcing steel"); p.work_package_id = 273
    p.spec_choice = {"selected": "Acme Rebar", "pinned": True, "picks": {}}
    p.plugs_removed = {"61": [{"assembly_id": 3617, "component_id": 9001, "name": "01 Rebar furnished and placed"}]}
    p.quotes["acme-rebar--reinforcing-steel.json"] = QuoteSync(55, 2, 4722, "ab" * 32, {"61": 901})
    sc.save(tmp_path / "bm-sync.json")
    again = Sidecar.load(tmp_path / "bm-sync.json")
    assert again.package("Reinforcing steel").quotes["acme-rebar--reinforcing-steel.json"].lines == {"61": 901}
    assert again.package("Reinforcing steel").plugs_removed == {
        "61": [{"assembly_id": 3617, "component_id": 9001, "name": "01 Rebar furnished and placed"}]}
    assert again.project_id == 1234 and again.estimate_id == 100
    assert again.package("Reinforcing steel").spec_choice["pinned"] is True
    assert json.loads((tmp_path / "bm-sync.json").read_text())["packages"]["Reinforcing steel"]["work_package_id"] == 273


def test_save_format(tmp_path):
    path = tmp_path / "bm-sync.json"
    sc = Sidecar(); sc.package("B"); sc.package("A")
    sc.save(path)
    text = path.read_text()
    assert text.endswith("}\n") and '\n  "packages"' in text
    assert text.index('"A"') < text.index('"B"')


def test_choice_of_defaults():
    assert choice_of({"name": "x"}) == {"selected": "ARR", "pinned": False, "picks": {}}
    assert choice_of({"selected": "Acme", "pinned": True, "picks": {"61": "ARR"}})["pinned"] is True
    assert choice_of({"picks": {61: "Acme"}})["picks"] == {"61": "Acme"}   # YAML int keys


def test_file_sha(tmp_path):
    f = tmp_path / "q.json"; f.write_bytes(b"abc")
    assert file_sha(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_legacy_plugs_removed_strings_load_as_dicts_without_a_name(tmp_path):
    """#428: a sidecar written before the change holds "<assembly_id>:<component_id>"
    strings; they load as the dict form with no name and are saved as dicts."""
    path = tmp_path / "bm-sync.json"
    path.write_text(json.dumps({"project_id": 1, "estimate_id": 2, "packages": {
        "Reinforcing steel": {"plugs_removed": {"61": ["3617:9001"]}, "quotes": {}}}}))
    sc = Sidecar.load(path)
    assert sc.package("Reinforcing steel").plugs_removed == {
        "61": [{"assembly_id": 3617, "component_id": 9001, "name": None}]}
    sc.save(path)
    assert '"3617:9001"' not in path.read_text()
    assert Sidecar.load(path).package("Reinforcing steel").plugs_removed["61"][0]["component_id"] == 9001
