"""Work packages in the spec: migrate a bid's work-packages.yaml, tag the lines a
package prices, and report quote coverage."""
from __future__ import annotations

from dataclasses import dataclass, field

from estimating_tools.quotes.model import CanonicalQuote


def _kind(pkg: dict) -> str:
    return pkg.get("kind", "subcontract")


def _cost_type(pkg: dict) -> str:
    return "material" if _kind(pkg) == "supply" else "subcontract"


def init_packages(spec: dict, packages_yaml: dict) -> list[str]:
    """Copy `packages[]` of a work-packages.yaml into `spec["work_packages"]`."""
    if "work_packages" in spec:
        raise ValueError("the spec already has work_packages -- init only starts a new list")
    out, report = [], []
    for src in packages_yaml.get("packages") or []:
        pkg = {
            "name": src["name"],
            "kind": "supply" if src.get("strategy") == "self_perform" else "subcontract",
        }
        if src.get("strategy") not in (None, ""):
            pkg["strategy"] = src["strategy"]       # never `strategy: null`
        for key in ("scope", "items", "detail", "conditions"):
            if src.get(key) not in (None, "", [], {}):
                pkg[key] = [str(n) for n in src[key]] if key == "items" else src[key]
        pkg["selected"] = "ARR"
        out.append(pkg)
        report.append(f"added package '{pkg['name']}' ({pkg['kind']}, "
                      f"{len(pkg.get('items', []))} item(s))")
    spec["work_packages"] = out
    return report


@dataclass
class SyncReport:
    tagged: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)

    @property
    def changes(self) -> int:
        return len(self.tagged) + len(self.added)

    def lines(self) -> list[str]:
        return ([f"tagged {t}" for t in self.tagged] + [f"added {a}" for a in self.added]
                + [f"ambiguous {a}" for a in self.ambiguous])


def sync_package_lines(spec: dict) -> SyncReport:
    report = SyncReport()
    items = {str(i["item_no"]): i for i in spec.get("items") or []}
    for pkg in spec.get("work_packages") or []:
        name, ctype = pkg["name"], _cost_type(pkg)
        for n in map(str, pkg.get("items") or []):
            item = items.get(n)
            if item is None:
                continue
            blocks = item.get("labor") or []
            cands = [(b, ln) for b in blocks for ln in (b.get("lines") or [])
                     if ln.get("cost_type") == ctype]
            covered = any(ln.get("package") == name for b in blocks
                          for ln in (b.get("lines") or []))
            if covered:
                continue
            free = [ln for _, ln in cands if "package" not in ln]
            for ln in free:
                ln["package"] = name
                report.tagged.append(f"item '{n}' line '{ln.get('name')}' -> {name}")
            if free:
                continue
            if cands:
                other = cands[0][1].get("package")
                report.ambiguous.append(
                    f"{name}: item '{n}' -- its {ctype} lines already belong to {other}")
                continue
            if not blocks:
                report.ambiguous.append(f"{name}: item '{n}' -- it has no task to hold a line")
                continue
            blocks[0].setdefault("lines", []).append({
                "cost_type": ctype, "name": name, "qty": item.get("qty"),
                "uom": item.get("uom"), "unit_price": 0, "source": "plug",
                "vendor": name, "package": name})
            report.added.append(f"item '{n}' line '{name}' ({ctype} plug) -> {name}")
    return report


def _fold(name) -> str:
    return str(name or "").strip().casefold()


def package_coverage(spec: dict, quotes: list[CanonicalQuote]) -> list[str]:
    """Problems with a package's quote coverage: no quote, a quoted item
    outside the package, a package line nobody prices. A quote is matched to
    its package case-insensitively (as the spread does). A line is priced by
    a quote line that includes it (not an alternate), or by a quote with an
    `amount` (a lump sum covers every line it does not exclude)."""
    out = []
    items = {str(i["item_no"]): i for i in spec.get("items") or []}
    for pkg in spec.get("work_packages") or []:
        name, listed = pkg["name"], [str(n) for n in pkg.get("items") or []]
        mine = [q for q in quotes if _fold(q.work_package_name) == _fold(name)]
        if not mine:
            out.append(f"{name}: no quote")
            continue
        for q in mine:
            for ln in q.lines:
                if str(ln.item_number) not in listed:
                    out.append(f"{name}: {q.vendor_name} quotes item '{ln.item_number}' "
                               f"which is not in the package")

        def prices(q, n, lname):
            base = [ql for ql in q.lines if str(ql.item_number) == n and not ql.is_alternate
                    and ql.line_name in (None, lname)]
            if any(ql.is_included for ql in base):
                return True
            return q.amount is not None and not base     # a lump sum, this line not excluded

        for n in listed:
            item = items.get(n)
            if item is None:
                continue
            for block in item.get("labor") or []:
                for ln in block.get("lines") or []:
                    if ln.get("package") != name:
                        continue
                    lname = ln.get("name")
                    if not any(prices(q, n, lname) for q in mine):
                        out.append(f"{name}: item '{n}' line '{lname}' priced by nobody")
    return out
