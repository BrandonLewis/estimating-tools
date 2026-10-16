import pytest

from estimating_tools.directory.excel import (
    build_directory, build_directory_from_excel, read_directory_rows,
)
from estimating_tools.directory.model import CanonicalDirectory


def test_identity_mapping_groups_org_with_contacts():
    rows = [
        {"organization": "Acme Paving", "region": "West", "is_dbe": "yes",
         "contact_email": "jane@acme.com", "first_name": "Jane", "role": "estimator"},
        {"organization": "Acme Paving", "region": "West", "is_dbe": "yes",
         "contact_email": "bob@acme.com", "first_name": "Bob", "role": "pm"},
    ]
    d = build_directory(rows)
    assert isinstance(d, CanonicalDirectory)
    assert len(d.organizations) == 1
    o = d.organizations[0]
    assert o.name == "Acme Paving" and o.region == "West" and o.is_dbe is True
    assert [(c.email, c.first_name, c.role) for c in o.contacts] == [
        ("jane@acme.com", "Jane", "estimator"),
        ("bob@acme.com", "Bob", "pm"),
    ]


def test_org_level_fields_from_first_row_when_rows_diverge():
    # org-level fields come from the FIRST row of the group; later rows' org-level
    # values are ignored (only their contacts are added).
    rows = [
        {"organization": "Acme", "region": "West", "is_dbe": "yes", "contact_email": "a@acme.com"},
        {"organization": "Acme", "region": "East", "is_dbe": "no", "contact_email": "b@acme.com"},
    ]
    o = build_directory(rows).organizations[0]
    assert o.region == "West" and o.is_dbe is True          # first row wins
    assert [c.email for c in o.contacts] == ["a@acme.com", "b@acme.com"]


def test_custom_mapping_reads_org_columns():
    rows = [{"Company": "Acme", "Cert #": "D123", "Email": "j@acme.com", "Title": "Owner"}]
    mapping = {"organization": "Company", "certification_number": "Cert #",
               "contact_email": "Email", "job_title": "Title"}
    d = build_directory(rows, mapping)
    o = d.organizations[0]
    assert o.name == "Acme" and o.certification_number == "D123"
    assert o.contacts[0].email == "j@acme.com" and o.contacts[0].job_title == "Owner"


def test_org_only_row_has_no_contacts():
    rows = [{"organization": "Solo Co", "contact_email": ""}]
    d = build_directory(rows)
    assert d.organizations[0].name == "Solo Co"
    assert d.organizations[0].contacts == []


def test_contacts_deduped_by_email_within_org():
    rows = [
        {"organization": "Acme", "contact_email": "j@acme.com", "first_name": "Jane"},
        {"organization": "Acme", "contact_email": "J@ACME.COM", "first_name": "Janet"},
    ]
    o = build_directory(rows).organizations[0]
    assert [c.email for c in o.contacts] == ["j@acme.com"]   # first-seen wins, case-insensitive


def test_is_dbe_truthy_parse():
    rows = [
        {"organization": "A", "is_dbe": "Yes", "contact_email": "a@x.com"},
        {"organization": "B", "is_dbe": "no", "contact_email": "b@x.com"},
        {"organization": "C", "is_dbe": "x", "contact_email": "c@x.com"},
        {"organization": "D", "contact_email": "d@x.com"},
        {"organization": "E", "is_dbe": "y", "contact_email": "e@x.com"},
        {"organization": "F", "is_dbe": "true", "contact_email": "f@x.com"},
        {"organization": "G", "is_dbe": "1", "contact_email": "g@x.com"},
        {"organization": "H", "is_dbe": "DBE", "contact_email": "h@x.com"},
        {"organization": "I", "is_dbe": "maybe", "contact_email": "i@x.com"},
    ]
    flags = {o.name: o.is_dbe for o in build_directory(rows).organizations}
    assert flags == {"A": True, "B": False, "C": True, "D": False,
                     "E": True, "F": True, "G": True, "H": True, "I": False}


def test_role_normalized_and_unknown_role_raises():
    ok = build_directory([{"organization": "A", "contact_email": "a@x.com", "role": "Estimator"}])
    assert ok.organizations[0].contacts[0].role == "estimator"
    with pytest.raises(ValueError, match=r"wizard|A"):
        build_directory([{"organization": "A", "contact_email": "a@x.com", "role": "wizard"}])


def test_blank_role_is_empty_string():
    o = build_directory([{"organization": "A", "contact_email": "a@x.com", "role": ""}]).organizations[0]
    assert o.contacts[0].role == ""


def test_missing_required_organization_column_raises():
    rows = [{"org_typo": "A", "contact_email": "a@x.com"}]
    with pytest.raises(ValueError):
        build_directory(rows)


def test_blank_organization_row_skipped_and_empty_is_empty():
    rows = [
        {"organization": "", "contact_email": "skip@x.com"},
        {"organization": "Real", "contact_email": "a@x.com"},
    ]
    d = build_directory(rows)
    assert [o.name for o in d.organizations] == ["Real"]
    assert build_directory([]).organizations == []


def test_org_phone_email_distinct_from_contact():
    rows = [{"organization": "Acme", "org_phone": "555-1000", "org_email": "info@acme.com",
             "contact_email": "jane@acme.com", "contact_phone": "555-2000"}]
    o = build_directory(rows).organizations[0]
    assert o.phone == "555-1000" and o.email == "info@acme.com"
    assert o.contacts[0].email == "jane@acme.com" and o.contacts[0].phone_primary == "555-2000"


def test_read_directory_rows_and_from_excel_roundtrip(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["organization", "is_dbe", "contact_email", "first_name", "role"])
    ws.append(["Acme Paving", "yes", "jane@acme.com", "Jane", "estimator"])
    ws.append(["Acme Paving", "yes", "bob@acme.com", "Bob", "pm"])
    path = tmp_path / "dir.xlsx"
    wb.save(path)

    rows = read_directory_rows(path)
    assert rows[0]["organization"] == "Acme Paving" and rows[0]["is_dbe"] == "yes"

    d = build_directory_from_excel(path)
    assert len(d.organizations) == 1 and len(d.organizations[0].contacts) == 2
