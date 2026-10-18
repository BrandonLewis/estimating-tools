"""est-addin manifest: the Office XML add-in-only manifest."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from estimating_tools.addin import brand as AB
from estimating_tools.addin import manifest as AM
from estimating_tools.addin.cli import main

NS = {"o": "http://schemas.microsoft.com/office/appforoffice/1.1",
      "ov": "http://schemas.microsoft.com/office/taskpaneappversionoverrides",
      "bt": "http://schemas.microsoft.com/office/officeappbasictypes/1.0"}
# BRAND_URL is what app_url derives to: two levels above it (see render_manifest).
BRAND_URL = "https://example.com/excel/addons/"
APP_URL = "https://example.com/excel/addons/navigator/1.0.0/"


def _render(**kw):
    args = {"app_url": APP_URL, "version": "1.0.0.0"} | kw
    return AM.render_manifest(AB.GENERIC, **args)


def test_the_manifest_carries_the_brand_and_urls():
    root = ET.fromstring(_render())
    assert root.find("o:DisplayName", NS).get("DefaultValue") == "Estimate Navigator"
    assert root.find("o:Version", NS).text == "1.0.0.0"
    assert root.find("o:IconUrl", NS).get("DefaultValue") == BRAND_URL + "assets/icon-32.png"
    assert root.find("o:HighResolutionIconUrl", NS).get("DefaultValue") == BRAND_URL + "assets/icon-64.png"
    assert root.find("o:DefaultSettings/o:SourceLocation", NS).get("DefaultValue") == APP_URL + "panes/taskpane.html"
    assert root.find("o:Permissions", NS).text == "ReadWriteDocument"
    assert root.find("o:Hosts/o:Host", NS).get("Name") == "Workbook"
    assert [s.get("Name") for s in root.findall("o:Requirements/o:Sets/o:Set", NS)] == ["ExcelApi"]
    labels = {s.get("id"): s.get("DefaultValue") for s in root.iter(f"{{{NS['bt']}}}String")}
    assert labels["Nav.ShortName"] == "Est. Navigator"


def test_two_slugs_give_different_ids():
    a = ET.fromstring(_render(slug="client-a"))
    b = ET.fromstring(_render(slug="client-b"))
    get = lambda r: r.find("o:Id", NS).text
    assert get(a) != get(b)


def test_the_id_is_stable_for_the_same_app_url_and_slug():
    a, b = ET.fromstring(_render()), ET.fromstring(_render())
    other = ET.fromstring(_render(app_url="https://other.example.com/excel/addons/navigator/1.0.0/"))
    get = lambda r: r.find("o:Id", NS).text
    assert get(a) == get(b) != get(other)


def test_case_and_port_spelling_give_the_same_id():
    a = ET.fromstring(_render(app_url="https://Example.com/excel/addons/navigator/1.0.0/"))
    b = ET.fromstring(_render(app_url="https://example.com:443/excel/addons/navigator/1.0.0/"))
    get = lambda r: r.find("o:Id", NS).text
    assert get(a) == get(b)


def test_a_slug_selects_the_brand_folder():
    root = ET.fromstring(_render(slug="client-a"))
    assert root.find("o:DefaultSettings/o:SourceLocation", NS).get("DefaultValue").endswith(
        "taskpane.html?brand=client-a")
    assert root.find("o:IconUrl", NS).get("DefaultValue") == \
        "https://example.com/excel/addons/client-a/assets/icon-32.png"


def test_text_is_escaped():
    brand = AB.GENERIC | {"name": 'A & B "Co"'}
    root = ET.fromstring(AM.render_manifest(brand, app_url=APP_URL, version="1.0.0.0"))
    assert root.find("o:DisplayName", NS).get("DefaultValue") == 'A & B "Co"'


@pytest.mark.parametrize("kw, message", [
    ({"app_url": "http://example.com/x/y/"}, "https"),
    ({"app_url": "https://example.com/x"}, "end with /"),
    ({"version": "1.0"}, "four"),
    ({"slug": "Bad Slug"}, "slug"),
])
def test_bad_arguments_are_refused(kw, message):
    with pytest.raises(AM.ManifestError, match=message):
        _render(**kw)


def test_an_app_url_with_userinfo_is_refused():
    with pytest.raises(AM.ManifestError, match="user info"):
        _render(app_url="https://user:pass@example.com/excel/addons/navigator/1.0.0/")


def test_an_app_url_without_a_host_is_refused():
    with pytest.raises(AM.ManifestError, match="host"):
        _render(app_url="https:///excel/addons/navigator/1.0.0/")


# -- M2/M3: _check_brand ------------------------------------------------------

def test_a_blank_required_field_is_refused():
    bad = AB.GENERIC | {"name": ""}
    with pytest.raises(AM.ManifestError, match="name"):
        AM.render_manifest(bad, app_url=APP_URL, version="1.0.0.0")


def test_an_insecure_support_url_is_refused():
    bad = AB.GENERIC | {"support_url": "http://example.com/help"}
    with pytest.raises(AM.ManifestError, match="support_url"):
        AM.render_manifest(bad, app_url=APP_URL, version="1.0.0.0")


def test_an_overlong_field_is_refused():
    bad = AB.GENERIC | {"short_name": "Way Too Long Short Name"}
    with pytest.raises(AM.ManifestError, match="short_name"):
        AM.render_manifest(bad, app_url=APP_URL, version="1.0.0.0")


def test_a_control_character_in_a_field_is_refused():
    bad = AB.GENERIC | {"description": "bad\x07text"}
    with pytest.raises(AM.ManifestError, match="description"):
        AM.render_manifest(bad, app_url=APP_URL, version="1.0.0.0")


def test_cli_writes_and_checks(tmp_path):
    brand = tmp_path / "brand.json"
    AB.write_brand(AB.GENERIC, tmp_path)
    out = tmp_path / "m.xml"
    args = ["manifest", "--brand", str(brand), "--app-url", APP_URL,
            "--version", "1.0.0.0", "-o", str(out)]
    assert main(args) == 0
    assert main([*args, "--check"]) == 0
    out.write_text(out.read_text(encoding="utf-8").replace("1.0.0.0", "9.9.9.9"), encoding="utf-8")
    assert main([*args, "--check"]) == 1
