"""Directory diff -> SyncPlan (estimating_tools.directory.diff)."""
from estimating_tools.directory.diff import build_sync_plan, render_sync_plan
from estimating_tools.directory.model import (
    CanonicalDirectory, DirectoryOrganization, DirectoryPerson)


def _local():
    return CanonicalDirectory(organizations=[
        DirectoryOrganization(name="ACME Rebar", phone="555-0100", contacts=[
            DirectoryPerson(email="joe@acmerebar.com", first_name="Joe"),
            DirectoryPerson(email="new@acmerebar.com", first_name="New"),
        ]),
        DirectoryOrganization(name="Local Only LLC"),
    ])


def _remote():
    return CanonicalDirectory(organizations=[
        DirectoryOrganization(name="acme rebar", phone="555-9999",
                              license_number="C-12345", contacts=[
            DirectoryPerson(email="joe@acmerebar.com", first_name="Joseph"),
        ]),
        DirectoryOrganization(name="Remote Only Inc", contacts=[
            DirectoryPerson(email="r@remote.com")]),
    ])


def test_creates_for_local_only_org_and_person():
    plan = build_sync_plan(_local(), _remote())
    kinds = {(c["kind"], c.get("org", c.get("email"))) for c in plan["creates"]}
    assert ("create_org", "Local Only LLC") in kinds
    assert ("create_person", "new@acmerebar.com") in kinds


def test_updates_only_differing_nonempty_local_fields():
    plan = build_sync_plan(_local(), _remote())
    org_updates = [u for u in plan["updates"] if u["kind"] == "update_org"]
    assert len(org_updates) == 1
    fields = org_updates[0]["fields"]
    assert fields["phone"] == {"remote": "555-9999", "local": "555-0100"}
    # local license_number is empty -> remote value NOT flagged for update
    assert "license_number" not in fields
    person_updates = [u for u in plan["updates"] if u["kind"] == "update_person"]
    assert person_updates[0]["fields"]["first_name"] == {
        "remote": "Joseph", "local": "Joe"}


def test_pulls_for_remote_only():
    plan = build_sync_plan(_local(), _remote())
    pulled = {p["org"] for p in plan["pulls"] if p["kind"] == "pull_org"}
    assert pulled == {"Remote Only Inc"}


def test_ambiguous_same_email_different_org():
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A", contacts=[
            DirectoryPerson(email="x@x.com")])])
    remote = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org B", contacts=[
            DirectoryPerson(email="x@x.com")])])
    plan = build_sync_plan(local, remote)
    assert plan["ambiguous"][0]["email"] == "x@x.com"
    assert plan["ambiguous"][0]["local_org"] == "Org A"
    assert plan["ambiguous"][0]["remote_org"] == "Org B"
    # ambiguous person is NOT also planned as a create
    assert not any(c.get("email") == "x@x.com" for c in plan["creates"])
    # ... not even nested inside the create_org payload
    assert plan["creates"][0]["data"]["contacts"] == []


def test_ambiguous_when_org_exists_on_both_sides():
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A", contacts=[
            DirectoryPerson(email="x@x.com")])])
    remote = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A"),
        DirectoryOrganization(name="Org B", contacts=[
            DirectoryPerson(email="x@x.com")])])
    plan = build_sync_plan(local, remote)
    amb = [a for a in plan["ambiguous"] if a["kind"] == "ambiguous_person"]
    assert amb[0]["email"] == "x@x.com"
    assert amb[0]["local_org"] == "Org A"
    assert amb[0]["remote_org"] == "Org B"
    assert not any(c.get("email") == "x@x.com" for c in plan["creates"])


def test_ambiguous_email_under_multiple_remote_orgs_names_them_all():
    # Cross-org: the same email under TWO remote orgs must surface both, not
    # silently keep whichever the dict comprehension saw last.
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org C", contacts=[
            DirectoryPerson(email="x@x.com")])])
    remote = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A", contacts=[
            DirectoryPerson(email="x@x.com")]),
        DirectoryOrganization(name="Org B", contacts=[
            DirectoryPerson(email="x@x.com")])])
    plan = build_sync_plan(local, remote)
    amb = [a for a in plan["ambiguous"] if a["kind"] == "ambiguous_person"]
    assert len(amb) == 1
    assert amb[0]["local_org"] == "Org C"
    assert amb[0]["remote_org"] == "Org A"          # first, deterministic
    assert amb[0]["remote_orgs"] == ["Org A", "Org B"]
    md = render_sync_plan(plan)
    assert "Org A" in md and "Org B" in md
    # still never planned
    assert not any(c.get("email") == "x@x.com" for c in plan["creates"])


def test_duplicate_org_names_in_one_file_are_surfaced():
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="ACME Rebar"),
        DirectoryOrganization(name="acme rebar"),
    ])
    plan = build_sync_plan(local, CanonicalDirectory())
    dups = [a for a in plan["ambiguous"] if a["kind"] == "duplicate_org"]
    assert len(dups) == 1
    assert dups[0]["org"].casefold() == "acme rebar"
    # plan body keeps last-wins: exactly one create_org for the name
    assert len([c for c in plan["creates"] if c["kind"] == "create_org"]) == 1
    assert "duplicate org" in render_sync_plan(plan)


def test_duplicate_person_emails_in_one_org_are_surfaced():
    remote = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Remote Only Inc", contacts=[
            DirectoryPerson(email="r@remote.com", first_name="R1"),
            DirectoryPerson(email="R@REMOTE.COM", first_name="R2"),
        ])])
    plan = build_sync_plan(CanonicalDirectory(), remote)
    dups = [a for a in plan["ambiguous"] if a["kind"] == "duplicate_person"]
    assert len(dups) == 1
    assert dups[0]["email"].casefold() == "r@remote.com"
    assert dups[0]["org"] == "Remote Only Inc"
    assert "duplicate person" in render_sync_plan(plan)


def test_empty_email_never_matched_or_ambiguated_across_orgs():
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A", contacts=[
            DirectoryPerson(email="", first_name="Anon")])])
    remote = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org B", contacts=[
            DirectoryPerson(email="")])])
    plan = build_sync_plan(local, remote)
    assert plan["ambiguous"] == []
    # the empty-email contact rides inside its org's create payload as-is
    creates = [c for c in plan["creates"] if c["kind"] == "create_org"]
    assert creates[0]["data"]["contacts"][0]["first_name"] == "Anon"


def test_empty_email_local_contact_in_matched_org_surfaced_not_planned():
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A", contacts=[
            DirectoryPerson(email="", first_name="Anon", last_name="Ymous")])])
    remote = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A")])
    plan = build_sync_plan(local, remote)
    assert not any(c["kind"] == "create_person" for c in plan["creates"])
    assert plan["ambiguous"] == [{
        "kind": "invalid_person", "org": "Org A", "source": "local",
        "name": "Anon Ymous"}]
    md = render_sync_plan(plan)
    assert "Anon Ymous" in md and "## Ambiguous" in md


def test_empty_email_remote_contact_in_matched_org_surfaced_not_pulled():
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A")])
    remote = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="Org A", contacts=[
            DirectoryPerson(email="")])])
    plan = build_sync_plan(local, remote)
    assert plan["pulls"] == []
    assert len(plan["ambiguous"]) == 1
    assert plan["ambiguous"][0]["kind"] == "invalid_person"
    assert plan["ambiguous"][0]["source"] == "remote"
    assert plan["ambiguous"][0]["org"] == "Org A"


def test_whitespace_org_name_is_surfaced_not_created():
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="   ")])
    plan = build_sync_plan(local, CanonicalDirectory())
    assert plan["creates"] == []
    assert plan["ambiguous"][0]["kind"] == "invalid_org"


def test_no_deletes_ever():
    plan = build_sync_plan(_local(), _remote())
    for section in plan.values():
        for change in section:
            assert "delete" not in change["kind"]


def test_render_plan_sections():
    md = render_sync_plan(build_sync_plan(_local(), _remote()))
    assert "## Creates" in md and "Local Only LLC" in md
    assert "## Updates (BM staff-gated)" in md and "555-0100" in md
    assert "## Pulls (into the local directory)" in md and "Remote Only Inc" in md


def test_render_create_org_lists_nested_contacts():
    local = CanonicalDirectory(organizations=[
        DirectoryOrganization(name="New Co", contacts=[
            DirectoryPerson(email="a@x.com"),
            DirectoryPerson(email="b@x.com")])])
    md = render_sync_plan(build_sync_plan(local, CanonicalDirectory()))
    assert "+ 2 contacts: a@x.com, b@x.com" in md
