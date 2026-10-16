from estimating_tools.directory.model import (
    CanonicalDirectory, DirectoryOrganization, DirectoryPerson, VALID_ROLES,
)


def test_models_construct_with_defaults():
    p = DirectoryPerson(email="jane@example.com")
    assert p.first_name == "" and p.last_name == "" and p.role == ""
    o = DirectoryOrganization(name="Acme Paving")
    assert o.is_dbe is False and o.contacts == [] and o.region == ""
    d = CanonicalDirectory()
    assert d.organizations == []


def test_org_holds_contacts():
    o = DirectoryOrganization(name="Acme", contacts=[DirectoryPerson(email="a@x.com")])
    assert o.contacts[0].email == "a@x.com"


def test_valid_roles_are_the_eight_bidmanager_roles():
    assert VALID_ROLES == {
        "prime_contact", "engineer", "pm", "superintendent",
        "estimator", "executive", "sales", "other",
    }
