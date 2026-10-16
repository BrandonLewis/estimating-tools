"""Directory diff — local CanonicalDirectory vs a BM export, producing a
reviewable SyncPlan (the bm-sync plan-then-execute idiom).

Identity rules match the importer: orgs by casefold name, persons by
casefold email. NO deletes in either direction — the directory is
find-or-create ground truth. Updates propose only non-empty local fields
that differ from remote (empty local = no opinion). Pulls surface
remote-only entries as additions to the LOCAL file, never BM writes.
Ambiguous (same email, different org), duplicate identities within one
file, and invalid (whitespace-only) org names are always surfaced in the
plan's ambiguous section, never planned. Empty emails are never identity
keys: such contacts ride inside their org's create/pull payloads as-is;
in an org present on BOTH sides they are surfaced as invalid_person,
never planned (nothing to match them against, so planning them would
re-plan forever)."""
from __future__ import annotations

from dataclasses import asdict

from estimating_tools.directory.model import CanonicalDirectory

_ORG_FIELDS = ("region", "license_number", "bidder_id", "phone", "email",
               "address", "certification_number", "certifying_agency",
               "federal_id")
_PERSON_FIELDS = ("first_name", "last_name", "phone_primary", "job_title",
                  "role")


def _field_diffs(local_obj, remote_obj, fields) -> dict:
    out = {}
    for f in fields:
        lv, rv = getattr(local_obj, f), getattr(remote_obj, f)
        if lv and lv != rv:
            out[f] = {"remote": rv, "local": lv}
    return out


def build_sync_plan(local: CanonicalDirectory,
                    remote: CanonicalDirectory) -> dict:
    plan = {"creates": [], "updates": [], "pulls": [], "ambiguous": []}

    def _org_map(orgs, source: str) -> dict:
        """Casefold-keyed org map. Whitespace-only names and duplicate keys
        are surfaced as ambiguous (last duplicate wins in the plan body)."""
        out = {}
        for o in orgs:
            key = o.name.strip().casefold()
            if not key:
                plan["ambiguous"].append({"kind": "invalid_org",
                                          "org": o.name, "source": source})
                continue
            if key in out:
                plan["ambiguous"].append({"kind": "duplicate_org",
                                          "org": o.name, "source": source})
            out[key] = o
        return out

    def _flag_duplicate_persons(orgs, source: str) -> None:
        for o in orgs:
            seen = set()
            for p in o.contacts:
                key = p.email.strip().casefold()
                if not key:
                    continue  # empty email is never an identity key
                if key in seen:
                    plan["ambiguous"].append({"kind": "duplicate_person",
                                              "email": p.email,
                                              "org": o.name,
                                              "source": source})
                seen.add(key)

    remote_orgs = _org_map(remote.organizations, "remote")
    local_orgs = _org_map(local.organizations, "local")
    _flag_duplicate_persons(remote.organizations, "remote")
    _flag_duplicate_persons(local.organizations, "local")

    # email -> remote org names holding it (empty emails excluded). A list,
    # not last-wins: the same email under multiple remote orgs must surface
    # every org, and cross-org ambiguity for the earlier orgs must not be
    # silently dropped.
    remote_emails: dict[str, list[str]] = {}
    for o in remote.organizations:
        for p in o.contacts:
            ekey = p.email.strip().casefold()
            if ekey and o.name not in remote_emails.setdefault(ekey, []):
                remote_emails[ekey].append(o.name)

    def _invalid_person(p, org_name: str, source: str) -> dict:
        name = " ".join(x for x in (p.first_name, p.last_name) if x) \
            or repr(p.email)
        return {"kind": "invalid_person", "org": org_name,
                "source": source, "name": name}

    def _flag_ambiguous(lp, lorg) -> bool:
        """True if lp's email lives in a DIFFERENT remote org (surfaced,
        never planned). Empty emails are never matched across orgs."""
        ekey = lp.email.strip().casefold()
        if not ekey:
            return False
        other_orgs = remote_emails.get(ekey)
        if not other_orgs:
            return False
        entry = {"kind": "ambiguous_person", "email": lp.email,
                 "local_org": lorg.name, "remote_org": other_orgs[0]}
        if len(other_orgs) > 1:
            entry["remote_orgs"] = list(other_orgs)
        plan["ambiguous"].append(entry)
        return True

    for lkey, lorg in local_orgs.items():
        rorg = remote_orgs.get(lkey)
        if rorg is None:
            data = asdict(lorg)
            data["contacts"] = [asdict(lp) for lp in lorg.contacts
                                if not _flag_ambiguous(lp, lorg)]
            plan["creates"].append({"kind": "create_org", "org": lorg.name,
                                    "data": data})
            continue
        fields = _field_diffs(lorg, rorg, _ORG_FIELDS)
        if fields:
            plan["updates"].append({"kind": "update_org", "org": lorg.name,
                                    "fields": fields})
        rpersons = {p.email.strip().casefold(): p for p in rorg.contacts
                    if p.email.strip()}
        for lp in lorg.contacts:
            ekey = lp.email.strip().casefold()
            if not ekey:
                plan["ambiguous"].append(
                    _invalid_person(lp, lorg.name, "local"))
                continue
            rp = rpersons.get(ekey)
            if rp is None:
                if not _flag_ambiguous(lp, lorg):
                    plan["creates"].append({"kind": "create_person",
                                            "email": lp.email,
                                            "parent_org": lorg.name,
                                            "data": asdict(lp)})
                continue
            pfields = _field_diffs(lp, rp, _PERSON_FIELDS)
            if pfields:
                plan["updates"].append({"kind": "update_person",
                                        "email": lp.email, "org": lorg.name,
                                        "fields": pfields})

    for rkey, rorg in remote_orgs.items():
        if rkey not in local_orgs:
            plan["pulls"].append({"kind": "pull_org", "org": rorg.name,
                                  "data": asdict(rorg)})
        else:
            lpersons = {p.email.strip().casefold()
                        for p in local_orgs[rkey].contacts
                        if p.email.strip()}
            for rp in rorg.contacts:
                rkey_email = rp.email.strip().casefold()
                if not rkey_email:
                    plan["ambiguous"].append(
                        _invalid_person(rp, rorg.name, "remote"))
                    continue
                if rkey_email not in lpersons:
                    plan["pulls"].append({"kind": "pull_person",
                                          "email": rp.email,
                                          "org": rorg.name,
                                          "data": asdict(rp)})
    return plan


def render_sync_plan(plan: dict) -> str:
    lines = ["# Directory Sync Plan", ""]

    def _fields(fields: dict) -> str:
        return "; ".join(f"{f}: {v['remote']!r} -> {v['local']!r}"
                         for f, v in fields.items())

    lines += ["## Creates", ""]
    for c in plan["creates"]:
        if c["kind"] == "create_org":
            contacts = c["data"].get("contacts", [])
            if contacts:
                n = len(contacts)
                emails = ", ".join(p["email"] for p in contacts)
                lines.append(f"- org **{c['org']}** "
                             f"(+ {n} contact{'s' if n != 1 else ''}: "
                             f"{emails})")
            else:
                lines.append(f"- org **{c['org']}**")
        else:
            lines.append(f"- person **{c['email']}** in {c['parent_org']}")
    if not plan["creates"]:
        lines.append("_None._")
    lines += ["", "## Updates (BM staff-gated)", ""]
    for u in plan["updates"]:
        subject = u.get("org") if u["kind"] == "update_org" else \
            f"{u['email']} ({u['org']})"
        lines.append(f"- {subject}: {_fields(u['fields'])}")
    if not plan["updates"]:
        lines.append("_None._")
    lines += ["", "## Pulls (into the local directory)", ""]
    for p in plan["pulls"]:
        if p["kind"] == "pull_org":
            lines.append(f"- org **{p['org']}**")
        else:
            lines.append(f"- person **{p['email']}** in {p['org']}")
    if not plan["pulls"]:
        lines.append("_None._")
    if plan["ambiguous"]:
        lines += ["", "## Ambiguous — review by hand, never auto-applied", ""]
        for a in plan["ambiguous"]:
            if a["kind"] == "duplicate_org":
                lines.append(f"- duplicate org name **{a['org']}** "
                             f"in the {a['source']} file")
            elif a["kind"] == "duplicate_person":
                lines.append(f"- duplicate person **{a['email']}** "
                             f"in {a['org']} ({a['source']} file)")
            elif a["kind"] == "invalid_org":
                lines.append(f"- invalid org name {a['org']!r} "
                             f"in the {a['source']} file")
            elif a["kind"] == "invalid_person":
                lines.append(f"- person with no email ({a['name']}) "
                             f"in {a['org']} ({a['source']} file)")
            else:
                orgs = ", ".join(a.get("remote_orgs") or [a["remote_org"]])
                label = "remote orgs" if a.get("remote_orgs") else "remote org"
                lines.append(f"- **{a['email']}**: local org {a['local_org']} "
                             f"vs {label} {orgs}")
    return "\n".join(lines) + "\n"
