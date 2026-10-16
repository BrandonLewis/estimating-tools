"""Three-way quantity reconciliation: takeoff vs IFC Qtos vs BM estimate,
plus an optional measured-geometry (mesh) leg that verifies authored volumes
against tessellated solids.

Pure assembler — stdlib only, no I/O, no ifcopenshell. The CLI feeds it a
CanonicalTakeoff, an optional IFC-leg dict {global_id: {name, ifc_class,
qtys}} (see bim.ifc_takeoff.ifc_leg), an optional mesh-leg dict
{global_id: {name, ifc_class, mesh}} (see bim.ifc_mesh.mesh_leg), and an
optional validated BM snapshot (load_bm_snapshot). Element comparisons
happen in SI (element entries carry value_si; IFC qtys and mesh volumes are
SI by construction)."""
from __future__ import annotations

from dataclasses import dataclass, field

# Summary statuses, in precedence order (worst wins)
MISSING_IN_TAKEOFF = "MISSING IN TAKEOFF"
MISSING_IN_BM = "MISSING IN BM"
MISSING_IN_IFC = "MISSING IN IFC"
VARIANCE = "VARIANCE"
OK = "OK"

# Geometry (mesh-leg) statuses/flags — a SEPARATE axis from the three-way
# `status`; geometry findings never mutate the status precedence chain.
GEOM_VARIANCE = "GEOM VARIANCE"
NO_GEOMETRY = "NO GEOMETRY"
NO_AUTHORED_VOLUME = "NO AUTHORED VOLUME"
UNCLASSIFIED = "UNCLASSIFIED"
GEOM_NA = "n/a"

# Graduated verdict bands (Work Tools/ifc_qto.py:659-671) — a human-facing
# grade of how far the other legs stray from the takeoff. AUGMENTS the
# status chain above; never replaces it. Paid quantities govern for bidding.
VERDICT_AGREE_PCT = 2.0
VERDICT_CHECK_PCT = 10.0
VERDICT_MATERIAL_PCT = 40.0


def verdict(delta_pct: float | None, unit: str) -> tuple[str, str]:
    """(text, tier) verdict for a percent delta; tier is the xlsx fill
    ('green' | 'yellow' | 'red'). None = no comparable quantity."""
    if delta_pct is None:
        return "no paid item matched - review mapping", "yellow"
    d = abs(delta_pct)
    if unit == "EA" and d < 0.01:
        return "EXACT match", "green"
    if d <= VERDICT_AGREE_PCT:
        return "agrees (<=2%)", "green"
    if d <= VERDICT_CHECK_PCT:
        return "close (<=10%) - check assumptions", "green"
    if d <= VERDICT_MATERIAL_PCT:
        return "material variance - see model assumptions", "yellow"
    return "large variance - do NOT use for bidding", "red"


def _item_verdict(delta_bm_pct, delta_ifc_pct, unit) -> tuple[str, str]:
    """Worst-of the BM and IFC deltas (the conservative generalization of the
    Work tool's single modelled-vs-paid delta to the three-way audit)."""
    deltas = [d for d in (delta_bm_pct, delta_ifc_pct) if d is not None]
    worst = max(deltas, key=abs) if deltas else None
    return verdict(worst, unit)


@dataclass
class ItemAudit:
    item_key: str
    schedule: str | None
    item_number: str | None
    description: str
    unit: str
    takeoff_qty: float | None
    ifc_qty: float | None
    bm_qty: float | None
    delta_ifc_pct: float | None
    delta_bm_pct: float | None
    status: str
    element_count: int = 0
    structure_count: int = 0
    measured_qty: float | None = None
    delta_geom_pct: float | None = None
    geom_status: str = GEOM_NA
    verdict: str = ""
    verdict_tier: str = ""


@dataclass
class ElementAudit:
    item_key: str
    global_id: str | None
    name: str
    ifc_class: str | None
    section_type: str
    structure_id: str | None
    count: int
    length_ft: float | None
    width_ft: float | None
    height_ft: float | None
    measure: str | None
    takeoff_si: float | None
    ifc_si: float | None
    delta_flag: str          # OK | VARIANCE | MISSING IN IFC | LEGACY
    join: str                # "id" | "name" | "none"
    mesh_si: float | None = None
    geom_flag: str = GEOM_NA


FINDING_KINDS = ("no-elements", "legacy-row", "name-join", "duplicate-name",
                 "orphan-element", "missing-in-bm", "missing-in-takeoff",
                 "missing-in-ifc", "structure-mismatch", "variance",
                 "zero-takeoff", "unit-conflict",
                 "geometry-variance", "unclassified-geometry")


@dataclass
class AuditFinding:
    kind: str                # see FINDING_KINDS
    item_key: str            # "" for file-level findings
    detail: str

    def __post_init__(self):
        if self.kind not in FINDING_KINDS:
            raise ValueError(f"unknown finding kind {self.kind!r}")


@dataclass
class GeometryRow:
    """One measured element for the Geometry sheet. item_key is "" for
    geometry that appears in no takeoff row (unclassified/reference)."""
    item_key: str
    global_id: str | None
    name: str
    ifc_class: str | None
    authored_si: float | None    # the Gross/NetVolume compared against, m3
    mesh_si: float | None        # measured volume, m3
    delta_pct: float | None
    flag: str                    # OK | GEOM VARIANCE | NO AUTHORED VOLUME |
                                 # UNCLASSIFIED | REFERENCE
    plan_area_m2: float = 0.0
    len_m: float = 0.0
    wid_m: float = 0.0
    hgt_m: float = 0.0
    z_min_m: float = 0.0
    z_max_m: float = 0.0


@dataclass
class AuditReport:
    items: list = field(default_factory=list)        # [ItemAudit]
    elements: list = field(default_factory=list)     # [ElementAudit]
    geometry: list = field(default_factory=list)     # [GeometryRow]
    exceptions: list = field(default_factory=list)   # [AuditFinding]
    legs: dict = field(default_factory=dict)         # {"ifc","bm","mesh": bool}
    tol_pct: float = 1.0
    provenance: dict = field(default_factory=dict)


def load_bm_snapshot(data) -> dict:
    """Validate the skill-produced BM estimate snapshot; raise ValueError
    naming the offending item on any shape problem."""
    if not isinstance(data, dict):
        raise ValueError("BM snapshot must be a JSON object")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("BM snapshot is missing its 'items' list")
    seen_keys = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"items[{i}] must be an object")
        missing = [req for req in ("description", "unit", "estimate_qty")
                   if req not in it]
        if missing:
            raise ValueError(f"items[{i}] ({it.get('item_number') or '?'}) "
                             f"is missing " +
                             ", ".join(f"'{m}'" for m in missing))
        if not isinstance(it["estimate_qty"], (int, float)):
            raise ValueError(f"items[{i}]: estimate_qty must be a number, "
                             f"got {type(it['estimate_qty']).__name__}")
        structures = it.get("structures", [])
        if not isinstance(structures, list):
            raise ValueError(f"items[{i}]: 'structures' must be a list")
        for j, s in enumerate(structures):
            if not isinstance(s, dict):
                raise ValueError(f"items[{i}]: structures[{j}] must be an "
                                 f"object with a 'structure_id'")
        if it.get("item_number"):
            k = (it.get("schedule"), it["item_number"])
            if k in seen_keys:
                raise ValueError(
                    f"items[{i}]: duplicate item "
                    f"{it.get('schedule') or '-'}/{it['item_number']} — "
                    f"snapshot keys must be unique")
            seen_keys.add(k)
    return data


def _item_key(schedule, item_number, description) -> str:
    if item_number:
        return f"{schedule or '-'}/{item_number}"
    return f"desc:{description}"


def _pct(base: float | None, other: float | None) -> float | None:
    if base is None or other is None or base == 0:
        return None
    return round((other - base) / base * 100.0, 2)


def _reconcile_elements(rep, key, rows, ifc, names, tol_pct,
                        mesh=None, geom_tol_pct=0.5):
    """IFC leg for one item group: join each takeoff element to its IFC
    element (GlobalId first, unique unclaimed name as fallback), appending
    ElementAudit rows and findings to `rep`. When `mesh` is given, also
    compare each joined element's mesh volume against its authored
    Gross/NetVolume and append GeometryRow evidence. Returns
    (to_si, ifc_si_sum, complete, any_elements, elem_variance,
    mesh_si_sum, mesh_complete, vol_measured, elem_geom_variance)."""
    to_si = 0.0
    ifc_si_sum = 0.0
    complete = True
    any_elements = False
    elem_variance = False
    mesh_si_sum = 0.0
    mesh_complete = True
    vol_measured = True
    elem_geom_variance = False
    claimed: set = set()   # gids already taken by a name-join in this group
    for row in rows:
        if not row.elements:
            rep.exceptions.append(AuditFinding(
                "no-elements", key,
                f"row '{row.description}' has no element breakdown — "
                f"regenerate the takeoff with est-bim >= 0.1.32"))
            complete = False
            continue
        for e in row.elements:
            any_elements = True
            gid = e.get("global_id")
            join = "id" if gid else "name"
            info = None
            if gid:
                info = ifc.get(gid)
                claimed.add(gid)
            else:
                cands = names.get(e.get("name", ""), [])
                if len(cands) == 1 and cands[0] in claimed:
                    join = "none"
                    rep.exceptions.append(AuditFinding(
                        "duplicate-name", key,
                        f"element name '{e.get('name')}' matched an IFC "
                        f"element already claimed by another takeoff "
                        f"element — cannot join"))
                elif len(cands) == 1:
                    gid, info = cands[0], ifc[cands[0]]
                    claimed.add(gid)
                    rep.exceptions.append(AuditFinding(
                        "name-join", key,
                        f"element '{e.get('name')}' joined by name — "
                        f"no global_id in the takeoff"))
                elif len(cands) > 1:
                    join = "none"
                    rep.exceptions.append(AuditFinding(
                        "duplicate-name", key,
                        f"element name '{e.get('name')}' matches "
                        f"{len(cands)} IFC elements — cannot join"))
            measure = e.get("measure")
            t_si = e.get("value_si")
            i_si = (info["qtys"].get(measure)
                    if info and measure else None)
            if t_si is None:
                flag = "LEGACY"
                complete = False
                rep.exceptions.append(AuditFinding(
                    "legacy-row", key,
                    f"element '{e.get('name')}' predates measured "
                    f"values (no value_si) — IFC delta not computable"))
            elif info is None or join == "none":
                flag = MISSING_IN_IFC
                complete = False
                if info is None and join != "none":
                    rep.exceptions.append(AuditFinding(
                        "orphan-element", key,
                        f"takeoff element '{e.get('name')}' "
                        f"({gid or 'no global_id'}) not found in the IFC"))
            elif i_si is None:
                flag = MISSING_IN_IFC
                complete = False
                rep.exceptions.append(AuditFinding(
                    "missing-in-ifc", key,
                    f"element '{e.get('name')}' ({gid}): IFC element "
                    f"lacks quantity '{measure}'"))
            else:
                to_si += t_si
                ifc_si_sum += i_si
                if t_si == 0 and i_si != 0:
                    # zero base: _pct is None but the discrepancy is real
                    flag = VARIANCE
                    rep.exceptions.append(AuditFinding(
                        "variance", key,
                        f"element '{e.get('name')}': takeoff 0 vs "
                        f"IFC {i_si} SI"))
                else:
                    d = _pct(t_si, i_si)
                    flag = VARIANCE if (d is not None and
                                        abs(d) > tol_pct) else OK
            if flag == VARIANCE:
                elem_variance = True

            # ---- mesh leg: measured volume vs authored Gross/NetVolume ----
            mesh_si = None
            geom_flag = GEOM_NA
            geom_ref = None
            if mesh is not None:
                if measure not in ("GrossVolume", "NetVolume"):
                    vol_measured = False
                minfo = mesh.get(gid) if gid else None
                if minfo is None:
                    geom_flag = NO_GEOMETRY
                    mesh_complete = False
                else:
                    mesh_si = minfo["mesh"]["volume_m3"]
                    mesh_si_sum += mesh_si
                    q = info["qtys"] if info else {}
                    geom_ref = q.get("GrossVolume", q.get("NetVolume"))
                    if geom_ref is None:
                        geom_flag = NO_AUTHORED_VOLUME
                        mesh_complete = False
                    elif geom_ref == 0:
                        # zero base: pct undefined but real mesh volume is a
                        # real discrepancy
                        geom_flag = (GEOM_VARIANCE if mesh_si > 1e-9 else OK)
                    else:
                        d = abs(mesh_si - geom_ref) / geom_ref * 100.0
                        geom_flag = (GEOM_VARIANCE if d > geom_tol_pct
                                     else OK)
                    if geom_flag == GEOM_VARIANCE:
                        elem_geom_variance = True
                        rep.exceptions.append(AuditFinding(
                            "geometry-variance", key,
                            f"element '{e.get('name')}' ({gid}): mesh "
                            f"{mesh_si:.6f} m3 vs authored "
                            f"{(geom_ref or 0.0):.6f} m3 "
                            f"(tol ±{geom_tol_pct}%)"))
                    rep.geometry.append(GeometryRow(
                        item_key=key, global_id=gid,
                        name=e.get("name", ""),
                        ifc_class=(info or {}).get("ifc_class"),
                        authored_si=geom_ref, mesh_si=mesh_si,
                        delta_pct=_pct(geom_ref, mesh_si), flag=geom_flag,
                        plan_area_m2=minfo["mesh"]["plan_area_m2"],
                        len_m=minfo["mesh"]["len_m"],
                        wid_m=minfo["mesh"]["wid_m"],
                        hgt_m=minfo["mesh"]["hgt_m"],
                        z_min_m=minfo["mesh"]["z_min_m"],
                        z_max_m=minfo["mesh"]["z_max_m"]))
            rep.elements.append(ElementAudit(
                item_key=key, global_id=gid, name=e.get("name", ""),
                ifc_class=(info or {}).get("ifc_class"),
                section_type=e.get("section_type", ""),
                structure_id=row.structure_id,
                count=e.get("count", 1),
                length_ft=e.get("length_ft"),
                width_ft=e.get("width_ft"),
                height_ft=e.get("height_ft"),
                measure=measure, takeoff_si=t_si, ifc_si=i_si,
                delta_flag=flag, join=join,
                mesh_si=mesh_si, geom_flag=geom_flag))
    return (to_si, ifc_si_sum, complete, any_elements, elem_variance,
            mesh_si_sum, mesh_complete, vol_measured, elem_geom_variance)


def build_audit(takeoff, *, ifc: dict | None = None, bm: dict | None = None,
                mesh: dict | None = None, tol_pct: float = 1.0,
                geom_tol_pct: float = 0.5, provenance: dict | None = None):
    """Reconcile a CanonicalTakeoff against optional IFC, BM and mesh legs."""
    if mesh is not None and ifc is None:
        raise ValueError("mesh leg requires the ifc leg — pass ifc= as well")
    rep = AuditReport(legs={"ifc": ifc is not None, "bm": bm is not None,
                            "mesh": mesh is not None},
                      tol_pct=tol_pct, provenance=provenance or {})

    # -- group quantity rows by bid-item key ---------------------------------
    groups: dict[str, list] = {}
    for row in takeoff.rows:
        if row.kind != "quantity":
            continue
        groups.setdefault(
            _item_key(row.schedule, row.item_number, row.description),
            []).append(row)

    bm_items = {}
    if bm is not None:
        for it in bm["items"]:
            bm_items[_item_key(it.get("schedule"), it.get("item_number"),
                               it["description"])] = it

    names: dict[str, list] = {}   # IFC name -> [gid] index, built once
    if ifc is not None:
        for gid, info in ifc.items():
            names.setdefault(info["name"], []).append(gid)

    for key, rows in sorted(groups.items()):
        first = rows[0]
        units = {r.unit for r in rows}
        if len(units) > 1:
            rep.exceptions.append(AuditFinding(
                "unit-conflict", key,
                f"rows for this item mix units {sorted(units)} — cannot sum"))
            takeoff_qty = None
        else:
            takeoff_qty = round(sum(r.quantity for r in rows), 4)
        bm_it = bm_items.pop(key, None)
        bm_qty = bm_it["estimate_qty"] if bm_it else None
        status = OK

        if takeoff_qty == 0 and (bm is not None or ifc is not None):
            rep.exceptions.append(AuditFinding(
                "zero-takeoff", key,
                "takeoff quantity is 0 — percent deltas not computable"))
        delta_bm = _pct(takeoff_qty, bm_qty)
        if bm is not None and bm_it is None:
            status = MISSING_IN_BM
            rep.exceptions.append(AuditFinding(
                "missing-in-bm", key,
                f"takeoff item '{first.description}' has no BM estimate item"))
        elif delta_bm is not None and abs(delta_bm) > tol_pct:
            status = VARIANCE
            rep.exceptions.append(AuditFinding(
                "variance", key,
                f"BM {bm_qty} vs takeoff {takeoff_qty} {first.unit} "
                f"({delta_bm:+.2f}% > ±{tol_pct}%)"))
        if takeoff_qty == 0 and bm_qty not in (None, 0) and status == OK:
            # zero base: delta_bm is None but the discrepancy is real
            status = VARIANCE

        to_structs = {r.structure_id for r in rows if r.structure_id}
        bm_structs = ({s.get("structure_id") for s in bm_it.get("structures", [])}
                      if bm_it else set())
        if bm_it and to_structs and bm_structs and to_structs != bm_structs:
            rep.exceptions.append(AuditFinding(
                "structure-mismatch", key,
                f"takeoff structures {sorted(to_structs)} != BM {sorted(bm_structs)}"))

        ifc_qty = None
        delta_ifc = None
        measured_qty = None
        delta_geom = None
        geom_status = GEOM_NA
        if ifc is not None:
            (to_si, ifc_si_sum, complete, any_elements, elem_variance,
             mesh_si_sum, mesh_complete, vol_measured,
             elem_geom_variance) = _reconcile_elements(
                rep, key, rows, ifc, names, tol_pct, mesh, geom_tol_pct)
            if (any_elements and complete and to_si > 0
                    and takeoff_qty is not None):
                # exact proportional display: row qty scaled by SI ratio
                ifc_qty = round(takeoff_qty * ifc_si_sum / to_si, 4)
                delta_ifc = _pct(takeoff_qty, ifc_qty)
                if delta_ifc is not None and abs(delta_ifc) > tol_pct:
                    if status == OK:
                        status = VARIANCE
                    rep.exceptions.append(AuditFinding(
                        "variance", key,
                        f"IFC {ifc_qty} vs takeoff {takeoff_qty} "
                        f"{first.unit} ({delta_ifc:+.2f}% > ±{tol_pct}%)"))
            elif not complete and status == OK:
                status = MISSING_IN_IFC
            if elem_variance and status == OK:
                status = VARIANCE
            if mesh is not None and any_elements:
                if not vol_measured:
                    geom_status = GEOM_NA
                elif (not (complete and mesh_complete) or to_si <= 0
                        or takeoff_qty is None):
                    geom_status = NO_GEOMETRY
                else:
                    measured_qty = round(
                        takeoff_qty * mesh_si_sum / to_si, 4)
                    delta_geom = _pct(takeoff_qty, measured_qty)
                    geom_status = (GEOM_VARIANCE if elem_geom_variance
                                   else OK)

        # Verdict only means something when a comparison leg was requested;
        # takeoff-only audits leave it blank (mirrors the geom_status n/a).
        v_text, v_tier = "", ""
        if bm is not None or ifc is not None:
            v_text, v_tier = _item_verdict(delta_bm, delta_ifc, first.unit)
        rep.items.append(ItemAudit(
            item_key=key, schedule=first.schedule,
            item_number=first.item_number, description=first.description,
            unit=first.unit, takeoff_qty=takeoff_qty,
            ifc_qty=ifc_qty, bm_qty=bm_qty,
            delta_ifc_pct=delta_ifc, delta_bm_pct=delta_bm, status=status,
            element_count=sum(len(r.elements or []) for r in rows),
            structure_count=len(to_structs or bm_structs),
            measured_qty=measured_qty, delta_geom_pct=delta_geom,
            geom_status=geom_status, verdict=v_text, verdict_tier=v_tier))

    if ifc is not None:
        referenced = {e.global_id for e in rep.elements if e.global_id}
        measured_classes = {e.ifc_class for e in rep.elements if e.ifc_class}
        for gid, info in sorted(ifc.items()):
            if gid not in referenced and info["ifc_class"] in measured_classes:
                rep.exceptions.append(AuditFinding(
                    "orphan-element", "",
                    f"IFC {info['ifc_class']} '{info['name']}' ({gid}) is "
                    f"in the model but in no takeoff row"))

    if mesh is not None:
        referenced = {e.global_id for e in rep.elements if e.global_id}
        n_uncl = 0
        for gid, info in sorted(mesh.items()):
            if gid in referenced:
                continue
            vol = info["mesh"]["volume_m3"]
            if vol > 1e-9:
                n_uncl += 1
                flag = UNCLASSIFIED
                rep.exceptions.append(AuditFinding(
                    "unclassified-geometry", "",
                    f"IFC {info['ifc_class']} '{info['name']}' ({gid}) "
                    f"carries {vol:.6f} m3 of geometry but appears in no "
                    f"takeoff row"))
            else:
                flag = "REFERENCE"
            rep.geometry.append(GeometryRow(
                item_key="", global_id=gid, name=info["name"],
                ifc_class=info["ifc_class"], authored_si=None, mesh_si=vol,
                delta_pct=None, flag=flag,
                plan_area_m2=info["mesh"]["plan_area_m2"],
                len_m=info["mesh"]["len_m"], wid_m=info["mesh"]["wid_m"],
                hgt_m=info["mesh"]["hgt_m"],
                z_min_m=info["mesh"]["z_min_m"],
                z_max_m=info["mesh"]["z_max_m"]))
        rep.provenance["mesh_counts"] = {
            "meshed": len(mesh),
            "qto_only": sum(1 for g in (ifc or {}) if g not in mesh),
            "unclassified": n_uncl}
        rep.provenance["geom_tol_pct"] = geom_tol_pct

    # BM items never matched by a takeoff row
    for key, it in sorted(bm_items.items()):
        rep.exceptions.append(AuditFinding(
            "missing-in-takeoff", key,
            f"BM item '{it['description']}' ({it['estimate_qty']} "
            f"{it['unit']}) has no takeoff row"))
        # These rows HAVE a real paid (BM) item — it's the takeoff side that
        # is missing, so the verdict wording points at the takeoff mapping.
        rep.items.append(ItemAudit(
            item_key=key, schedule=it.get("schedule"),
            item_number=it.get("item_number"), description=it["description"],
            unit=it["unit"], takeoff_qty=None, ifc_qty=None,
            bm_qty=it["estimate_qty"], delta_ifc_pct=None, delta_bm_pct=None,
            status=MISSING_IN_TAKEOFF,
            structure_count=len(it.get("structures", [])),
            verdict="no takeoff row - review mapping", verdict_tier="yellow"))
    return rep
