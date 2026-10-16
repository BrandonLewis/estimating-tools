"""CanonicalDirectory dict round-trip (for JSON exports/diffs)."""
from estimating_tools.directory.model import (
    CanonicalDirectory, DirectoryOrganization, DirectoryPerson)


def test_round_trip():
    d = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="ACME Rebar", phone="555-0100", contacts=[
            DirectoryPerson(email="joe@acmerebar.com", first_name="Joe",
                            role="estimator")]),
    ])
    d2 = CanonicalDirectory.from_dict(d.to_dict())
    assert d2 == d
    assert d2.organizations[0].contacts[0].email == "joe@acmerebar.com"


def test_from_dict_tolerates_missing_fields():
    d = CanonicalDirectory.from_dict(
        {"organizations": [{"name": "Basalt Steel",
                            "contacts": [{"email": "a@b.c"}]}]})
    assert d.organizations[0].contacts[0].first_name == ""
