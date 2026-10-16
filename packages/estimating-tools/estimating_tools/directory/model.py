"""The open directory model — an org's vendors/subs/primes and their contacts.
Pure: stdlib only. Fields map to BidSheet.ai's create_organization / create_person."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# The roles BidSheet.ai accepts for a person-in-organization affiliation.
VALID_ROLES = {
    "prime_contact", "engineer", "pm", "superintendent",
    "estimator", "executive", "sales", "other",
}


@dataclass
class DirectoryPerson:
    """A contact. email is the unique key in BidSheet.ai. role (if set) is one of
    VALID_ROLES and describes the person's affiliation with the parent org."""

    email: str
    first_name: str = ""
    last_name: str = ""
    phone_primary: str = ""
    job_title: str = ""
    role: str = ""


@dataclass
class DirectoryOrganization:
    """A company (prime/sub/vendor/agency). name is the dedup key (case-insensitive in
    BidSheet.ai). is_dbe + the certification_* fields carry DBE status."""

    name: str
    region: str = ""
    license_number: str = ""
    bidder_id: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    is_dbe: bool = False
    certification_number: str = ""
    certifying_agency: str = ""
    federal_id: str = ""
    contacts: list[DirectoryPerson] = field(default_factory=list)


@dataclass
class CanonicalDirectory:
    """An org's directory of organizations + their contacts."""

    organizations: list[DirectoryOrganization] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CanonicalDirectory":
        orgs = []
        for o in data.get("organizations", []):
            contacts = [DirectoryPerson(**p) for p in o.get("contacts", [])]
            orgs.append(DirectoryOrganization(
                **{k: v for k, v in o.items() if k != "contacts"},
                contacts=contacts))
        return cls(organizations=orgs)
