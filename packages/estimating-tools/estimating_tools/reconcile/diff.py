"""The reconciliation diff itself — pure, deterministic."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Union


@dataclass(frozen=True)
class LineItem:
    """One bid line: BM holds it at COST unit price, the contract at SELL."""

    item: str
    description: str = ""
    unit: str = ""
    quantity: float = 0.0
    unit_price: float = 0.0

    @property
    def total(self) -> float:
        return self.quantity * self.unit_price

    @classmethod
    def coerce(cls, row: Union["LineItem", dict]) -> "LineItem":
        if isinstance(row, LineItem):
            return row
        return cls(item=str(row["item"]),
                   description=row.get("description", ""),
                   unit=row.get("unit", ""),
                   quantity=float(row.get("quantity", 0) or 0),
                   unit_price=float(row.get("unit_price", 0) or 0))


@dataclass(frozen=True)
class ReconLine:
    item: str
    description: str
    unit: str
    quantity: float
    bm_unit_cost: float | None
    bm_cost_total: float | None
    bm_sell_total: float | None       # bm_cost_total * (1 + markup)
    contract_unit_price: float | None
    contract_total: float | None
    margin: float | None              # contract_total - bm_cost_total
    margin_pct: float | None          # margin / contract_total
    effective_markup: float | None    # contract_up / bm_unit_cost - 1
    status: str                       # matched | contract_only | bm_only
    flag: str = ""


@dataclass
class Reconciliation:
    lines: list[ReconLine]
    bm_cost_total: float
    contract_total: float
    margin: float
    margin_pct: float
    matched: int
    contract_only: int
    bm_only: int

    def by_status(self, status: str) -> list[ReconLine]:
        return [x for x in self.lines if x.status == status]


def _sort_key(item: str):
    # numeric items sort numerically; the raw string is a tie-breaker so
    # numeric-equal ids ("02" vs "2") keep a stable, input-independent order
    return (0, int(item), item) if item.isdigit() else (1, 0, item)


def _index(items: Iterable, side: str) -> dict[str, LineItem]:
    out: dict[str, LineItem] = {}
    for li in map(LineItem.coerce, items):
        if li.item in out:
            raise ValueError(
                f"duplicate item {li.item!r} in {side} — aggregate or de-dup "
                "before reconciling (a silent last-wins overwrite would skew "
                "the totals)")
        out[li.item] = li
    return out


def reconcile_contract_vs_estimate(
        bm_items: Iterable, contract_items: Iterable, *, markup: float = 0.0,
        flag_low: float | None = None, flag_high: float | None = None
        ) -> Reconciliation:
    """Diff an executed contract (SELL prices) against a BM estimate (COST).

    ``markup`` produces each matched line's ``bm_sell_total = bm_cost_total *
    (1+markup)``. ``flag_low``/``flag_high`` (optional, as effective-markup
    fractions) flag a matched line whose contract-over-cost markup falls outside
    ``[flag_low, flag_high]`` — the "this item's margin is nothing like the
    target" signal. Both thresholds are parameters; none is baked.

    Margin is measured against COST: ``margin = contract_total - bm_cost_total``,
    so a contract-only item (no BM cost yet) is full margin and surfaces as an
    add-to-estimate scope gap.
    """
    bm = _index(bm_items, "estimate")
    contract = _index(contract_items, "contract")

    lines: list[ReconLine] = []
    bm_cost_sum = contract_sum = margin_sum = 0.0

    matched_or_contract = sorted(contract, key=_sort_key)
    for item in matched_or_contract:
        c = contract[item]
        b = bm.get(item)
        c_total = c.total
        contract_sum += c_total
        if b is None:                              # in contract, not estimate
            margin_sum += c_total
            lines.append(ReconLine(
                item=item, description=c.description, unit=c.unit,
                quantity=c.quantity, bm_unit_cost=None, bm_cost_total=None,
                bm_sell_total=None, contract_unit_price=c.unit_price,
                contract_total=c_total, margin=c_total, margin_pct=1.0,
                effective_markup=None, status="contract_only",
                flag="in contract, not in estimate — add"))
            continue
        b_total = b.total
        bm_cost_sum += b_total
        margin = c_total - b_total
        margin_sum += margin
        eff = (c.unit_price / b.unit_price - 1) if b.unit_price else None
        flag = ""
        if eff is not None:
            if flag_low is not None and eff < flag_low:
                flag = f"eff. markup {eff:+.0%} below {flag_low:.0%}"
            elif flag_high is not None and eff > flag_high:
                flag = f"eff. markup {eff:+.0%} above {flag_high:.0%}"
        lines.append(ReconLine(
            item=item, description=c.description or b.description,
            unit=c.unit or b.unit, quantity=c.quantity,
            bm_unit_cost=b.unit_price, bm_cost_total=b_total,
            bm_sell_total=b_total * (1 + markup),
            contract_unit_price=c.unit_price, contract_total=c_total,
            margin=margin, margin_pct=(margin / c_total if c_total else 0.0),
            effective_markup=eff, status="matched", flag=flag))

    for item in sorted((i for i in bm if i not in contract), key=_sort_key):
        b = bm[item]
        lines.append(ReconLine(
            item=item, description=b.description, unit=b.unit,
            quantity=b.quantity, bm_unit_cost=b.unit_price,
            bm_cost_total=b.total, bm_sell_total=b.total * (1 + markup),
            contract_unit_price=None, contract_total=None, margin=None,
            margin_pct=None, effective_markup=None, status="bm_only",
            flag="in estimate, not in contract — remove/zero"))

    matched = sum(1 for x in lines if x.status == "matched")
    contract_only = sum(1 for x in lines if x.status == "contract_only")
    bm_only = sum(1 for x in lines if x.status == "bm_only")
    return Reconciliation(
        lines=lines, bm_cost_total=bm_cost_sum, contract_total=contract_sum,
        margin=margin_sum,
        margin_pct=(margin_sum / contract_sum if contract_sum else 0.0),
        matched=matched, contract_only=contract_only, bm_only=bm_only)


# ---------------------------------------------------------------------------
# deterministic text surfaces
# ---------------------------------------------------------------------------

_COLUMNS = ["Item", "Description", "Unit", "Qty", "BM cost U/P",
            "BM cost total", "BM sell", "Contract U/P", "Contract total",
            "Margin $", "Margin %", "Eff. markup", "Status", "Flag / note"]


def _fmt(v, pct: bool = False) -> str:
    if v is None:
        return ""
    if pct:
        return f"{v:.1%}"
    return f"{v:,.2f}"


def _row(x: ReconLine) -> list:
    return [
        x.item, x.description, x.unit, _fmt(x.quantity),
        _fmt(x.bm_unit_cost), _fmt(x.bm_cost_total), _fmt(x.bm_sell_total),
        _fmt(x.contract_unit_price), _fmt(x.contract_total),
        _fmt(x.margin), _fmt(x.margin_pct, pct=True),
        _fmt(x.effective_markup, pct=True), x.status, x.flag,
    ]


def to_rows(recon: Reconciliation) -> list[list]:
    """Header + one row per line, values as display strings (deterministic)."""
    return [list(_COLUMNS)] + [_row(x) for x in recon.lines]


def to_markdown(recon: Reconciliation) -> str:
    """A reviewer-facing reconciliation summary."""
    out = ["# Contract vs Estimate Reconciliation", "",
           f"- Matched: **{recon.matched}**  ·  in contract not estimate: "
           f"**{recon.contract_only}**  ·  in estimate not contract: "
           f"**{recon.bm_only}**",
           f"- BM cost (matched): **{recon.bm_cost_total:,.0f}**  ·  "
           f"contract: **{recon.contract_total:,.0f}**  ·  "
           f"margin: **{recon.margin:,.0f}** ({recon.margin_pct:.1%})", ""]

    def _esc(cell) -> str:
        # a caller description like "Concrete | Bridge" would otherwise open
        # extra columns and corrupt the table
        return str(cell).replace("\\", "\\\\").replace("|", "\\|")

    def _table(lines: list[ReconLine]) -> list[str]:
        body = ["| " + " | ".join(_esc(c) for c in _COLUMNS) + " |",
                "|" + "|".join(["---"] * len(_COLUMNS)) + "|"]
        for x in lines:
            body.append("| " + " | ".join(_esc(c) for c in _row(x)) + " |")
        return body

    matched = recon.by_status("matched")
    if matched:
        out += ["## Matched", ""] + _table(matched) + [""]
    add = recon.by_status("contract_only")
    if add:
        out += ["## IN CONTRACT, NOT IN ESTIMATE (add)", ""] + _table(add) + [""]
    drop = recon.by_status("bm_only")
    if drop:
        out += ["## IN ESTIMATE, NOT IN CONTRACT (remove/zero)", ""]
        out += _table(drop) + [""]
    out += [f"**TOTAL** — contract {recon.contract_total:,.0f}, "
            f"BM cost {recon.bm_cost_total:,.0f}, margin {recon.margin:,.0f} "
            f"({recon.margin_pct:.1%})", ""]
    return "\n".join(out)
