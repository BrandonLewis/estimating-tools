"""Independently price an estimate spec in pure Python, without opening Excel.

openpyxl writes formulas but never evaluates them, so a freshly generated
.xlsx has empty totals until someone opens it in Excel. This module replicates
the workbook's arithmetic straight from the *.estimate.yaml so the bid number
is known before that happens — and so the generated workbook has something to
be checked against.

The formula semantics mirrored here (from units.yaml):
    crew row      F = days x (rate x count) x 8
    block         subtotal = SUM(crew F)
    labor_total   = sum of block subtotals
    foreman_days  = SUMIF(trade == "FORE", days)
    spreads       qty_subtotal = ftg x (1+ftg_waste) + wall x (1+wall_waste)
                  (both waste factors come from the PACK's unit-param
                  defaults, or from the block; never a literal here)
    cost_detail   subtotal = header_price x item_qty + SUM(qty x unit_price)
                  ("=D{r-1}" carries the line above, e.g. TOOLS rides PICKUP)
    sub takeoff   material + galvanize + tax + freight
    item TOTAL    = labor + materials + cost_details + sub takeoff
    bid           = SUM(item TOTAL) + markup

{ref:...} targets resolve against a context built from whatever the spec
itself carries (geometry takeoff lines, labor slots, spreads); an unknown ref
is an error. Residual cell references ("{row:...}", "{r-1}", "$A$1") that
cannot be resolved without the rendered sheet carry forward gracefully (the
value's default is returned). Whatever arithmetic remains after substitution
runs through a sandboxed evaluator that refuses anything but numbers and
+ - * / ( ) — names, attributes, and subscripts never evaluate.

CAVEAT: a clean summarize run proves the spec's INTERNAL arithmetic is
consistent — it does NOT prove the rates are current. An independent rate
check against the BM rate library remains the estimator's job (the estimate5d
self-derived-gate lesson: a number derived from the spec cannot vouch for the
spec's own inputs).
"""
from __future__ import annotations

import re

HRS_PER_DAY = 8.0

_REF = re.compile(r"\{ref:([^{}]+)\}")
#: Mirrors build.SHEET_SEP. Spelled out rather than imported: this module
#: prices a spec in pure Python and does not pull openpyxl in to do it.
_SHEET_SEP = "!"
# Cell references we cannot resolve without the rendered sheet. Any column
# (the rate table lives at J/K), but never a float exponent: the letter must
# not ride a digit/point ("1.5E2" is 150, "2*E3" is a column-E ref).
_CELL_REF = re.compile(r"\{row:|\{r[-+]?\d*\}|(?<![\w.])\$?[A-Z]{1,2}\$?\d")
# After substitution only pure arithmetic may remain (digits, operators,
# parens, decimal points, float exponents, whitespace).
_ARITHMETIC = re.compile(r"^[0-9eE+\-*/(). \t]+$")


class FormulaError(ValueError):
    """A formula referenced an unknown target or refused the sandbox."""


_UNITS_DEFAULTS: dict[tuple, dict] = {}

#: The spreads legs this module's `qty_subtotal` arithmetic reads. A pack
#: whose spreads block names its legs something else is not summarizable by
#: this code, and must be told so rather than priced at zero.
_SPREAD_LEGS = (("ftg_qty", "ftg_waste"), ("wall_qty", "wall_waste"))


def _units_defaults(pack) -> dict:
    """Every `default:` declared by any unit param in the pack, by name."""
    defaults = _UNITS_DEFAULTS.get(pack.key)
    if defaults is None:
        defaults = _UNITS_DEFAULTS[pack.key] = {}
        for udef in pack.units.values():
            for name, pdef in (udef.get("params") or {}).items():
                if isinstance(pdef, dict) and "default" in pdef:
                    defaults.setdefault(name, pdef["default"])
    return defaults


def _units_default(param: str, fallback: float, pack=None) -> float:
    """A unit-param default straight from the pack's units, so summarize and
    the generator can never disagree on it (the build side injects these via
    _apply_defaults; tax_rate's 0.0725 was the divergence that motivated this)."""
    from estimating_tools.estimate_spec.format_pack import bundled_pack

    v = _units_defaults(pack or bundled_pack()).get(param, fallback)
    return float(v) if isinstance(v, (int, float)) else fallback


def _spreads_qty_subtotal(sp: dict, ctx: dict, pack, tag: str, carries) -> float:
    """`ftg x (1+ftg_waste) + wall x (1+wall_waste)`, with both waste factors
    read from the pack.

    The waste factors used to be literals — 0.15 and 0.125, one org's numbers,
    applied to every pack that declares `supports: summarize`. And a pack
    whose spreads block names its legs anything else scored `qty_subtotal = 0`
    in silence, which is a wrong bid number rather than an error. Both are
    refused here instead, naming the pack and the keys expected.
    """
    legs = [k for pair in _SPREAD_LEGS for k in pair]
    if not set(sp) & set(legs):
        raise FormulaError(
            f"{tag}: pack '{pack.name}' declares supports: summarize, but this "
            f"item's spreads block carries none of {legs} — summarize cannot "
            "read its quantity legs and will not price them as zero. Either "
            "the pack's spreads vocabulary is shaped differently (drop "
            "'summarize' from its supports:), or the block is empty.")
    declared = _units_defaults(pack)
    total = 0.0
    for qty_key, waste_key in _SPREAD_LEGS:
        qty = evaluate(sp.get(qty_key, 0), ctx, carries=carries,
                       where=f"{tag} spreads {qty_key}")
        if waste_key in sp:
            waste = float(sp[waste_key])
        elif isinstance(declared.get(waste_key), (int, float)):
            waste = float(declared[waste_key])
        else:
            raise FormulaError(
                f"{tag}: pack '{pack.name}' declares supports: summarize but "
                f"neither this spreads block nor the pack's units declare a "
                f"default for {waste_key!r}; summarize will not invent a waste "
                "factor. Give the unit param a default, or set it on the block.")
        total += qty * (1 + waste)
    return total


def evaluate(expr, ctx: dict, default: float = 0.0, *,
             carries: list | None = None, where: str = "") -> float:
    """Evaluate a config value: a number, or a small sandboxed formula string.

    {ref:KEY} substitutes from *ctx* (unknown KEY raises). Residual cell refs
    return *default* (carried forward — recorded in *carries* when given, so
    a load-bearing quantity silently pricing at the default is visible in the
    result instead of vanishing). Any remaining non-arithmetic residue raises
    FormulaError naming the offending expression.
    """
    if expr is None:
        return default
    if isinstance(expr, bool):
        # YAML turns yes/no/on/off into booleans; silently pricing True as
        # 1.0 turns a typo into a quantity. Refuse loudly.
        raise FormulaError(
            f"boolean {expr!r} is not a quantity"
            + (f" (at {where})" if where else ""))
    if isinstance(expr, (int, float)):
        return float(expr)
    s = str(expr).strip().lstrip("=")

    def _sub(m: re.Match) -> str:
        key = m.group(1).strip()
        if key not in ctx:
            if _SHEET_SEP in key:
                # A cross-sheet ref is a WORKBOOK address; this module prices
                # from the spec alone and has no other sheet to read. Say which
                # kind of mistake it is, so the author knows whether to fix a
                # typo or move the value into the pack's unit template.
                raise FormulaError(
                    f"cross-sheet ref {{ref:{key}}} in formula {str(expr)!r}: a "
                    "cross-sheet ref resolves only while the workbook is being "
                    "rendered, so an estimate spec cannot carry one -- it "
                    "belongs in the pack's unit template")
            raise FormulaError(
                f"unknown ref {{ref:{key}}} in formula {str(expr)!r}")
        return f"({float(ctx[key])!r})"

    s = _REF.sub(_sub, s)
    if _CELL_REF.search(s):
        if carries is not None:
            carries.append({"where": where, "formula": str(expr),
                            "default": default})
        return default          # sheet-relative address: carry forward
    if "**" in s:
        # exponentiation is never a workbook idiom here, and "=9**9**9**9"
        # is a CPU pit — refuse it with the rest of the non-arithmetic.
        raise FormulaError(
            f"refusing to evaluate non-arithmetic formula {str(expr)!r}")
    if not s or not _ARITHMETIC.fullmatch(s):
        raise FormulaError(
            f"refusing to evaluate non-arithmetic formula {str(expr)!r}")
    try:
        return float(eval(s, {"__builtins__": {}}, {}))  # noqa: S307 - whitelisted arithmetic only
    except Exception:
        raise FormulaError(
            f"refusing to evaluate non-arithmetic formula {str(expr)!r}") from None


def build_ctx(item: dict) -> dict:
    """Seed the {ref:...} context from the item's own geometry takeoff lines.

    Every numeric field across the lines sums into ``takeoff.<field>``; the
    workbook's total row (D+F / E+G) generalizes to ``takeoff.total_<suffix>``
    = sum of the ``*_<suffix>`` columns (e.g. ftg_cy + wall_cy -> total_cy).
    """
    ctx: dict[str, float] = {}
    t = item.get("takeoff") or {}
    if t.get("kind") == "geometry":
        lines = t.get("lines") or []
        fields: set[str] = set()
        for line in lines:
            fields.update(k for k, v in line.items()
                          if isinstance(v, (int, float))
                          and not isinstance(v, bool))
        for f in fields:
            ctx[f"takeoff.{f}"] = float(sum(line.get(f) or 0 for line in lines))
        for suffix in {f.rsplit("_", 1)[1] for f in fields if "_" in f}:
            ctx[f"takeoff.total_{suffix}"] = sum(
                ctx[f"takeoff.{f}"] for f in fields if f.endswith("_" + suffix))
    return ctx


def price_item(item: dict, rates: dict,
               carries: list | None = None, *, pack=None) -> dict:
    """Price one item; returns the per-item totals dict (see summarize)."""
    from estimating_tools.estimate_spec.format_pack import bundled_pack

    pack = pack or bundled_pack()
    foreman = (pack.vocabulary or {}).get("foreman_trade")
    ctx = build_ctx(item)
    tag = item.get("sheet") or item.get("item_no") or "?"
    out: dict = {"sheet": item.get("sheet", ""),
                 "item_no": item.get("item_no", ""),
                 "description": item.get("description", "")}

    # ---- labor ------------------------------------------------------------
    labor_total = 0.0
    manhours = 0.0
    foreman_days = 0.0
    blocks = []
    for blk in item.get("labor") or []:
        acts = blk.get("activities") or []
        default_factor = pack.labor["crew_factor_default"]
        crew_factor = blk.get("crew_factor", default_factor)
        prod_days = sum(a["factor"] for a in acts) * crew_factor if acts else 0.0
        ctx[f"labor[{blk['slot']}].prod_days"] = prod_days

        first_days = None
        sub = 0.0
        mh = 0.0
        for crew in blk.get("crew") or []:
            raw = crew["days"]
            if isinstance(raw, (int, float)):
                days = float(raw)
            elif "prod_days" in str(raw):
                days = prod_days
            elif "crew_first" in str(raw):
                days = first_days if first_days is not None else 0.0
            else:
                days = evaluate(raw, ctx, carries=carries,
                                where=f"{tag} labor[{blk['slot']}] "
                                      f"{crew['trade']} days")
            if first_days is None:
                first_days = days
            trade = crew["trade"]
            if trade not in rates:
                raise FormulaError(
                    f"unknown trade {trade!r} (not in rate_table)")
            count = crew.get("count", 1)
            sub += days * rates[trade] * count * HRS_PER_DAY
            mh += days * count * HRS_PER_DAY
            if trade == foreman:
                foreman_days += days
        ctx[f"labor[{blk['slot']}].driver"] = evaluate(
            blk.get("driver", 1), ctx, 1.0)
        blocks.append((blk["slot"], blk.get("description", ""), prod_days, sub))
        labor_total += sub
        manhours += mh

    ctx["labor_rollup.foreman_days"] = foreman_days
    out["labor_blocks"] = blocks
    out["labor_total"] = labor_total
    out["manhours"] = manhours
    out["foreman_days"] = foreman_days

    # ---- item qty ---------------------------------------------------------
    item_qty = evaluate(item.get("qty", 1), ctx, 1.0, carries=carries,
                        where=f"{tag} qty")
    out["qty"] = item_qty
    out["uom"] = item.get("uom", "")

    # ---- takeoff (subcontractor kind carries its own dollars) -------------
    sub_total = 0.0
    t = item.get("takeoff") or {}
    if t.get("kind") == "subcontractor":
        material = sum(evaluate(line["qty"], ctx)
                       * evaluate(line["unit_price"], ctx)
                       for line in t.get("lines") or [])
        galvanize = evaluate(t.get("galvanize", 0), ctx, carries=carries,
                             where=f"{tag} takeoff galvanize")
        tax = (material + galvanize) * float(
            t.get("tax_rate", _units_default("tax_rate", 0.0, pack)))
        freight = evaluate(t.get("freight", 0), ctx, carries=carries,
                           where=f"{tag} takeoff freight")
        sub_total = material + galvanize + tax + freight
        out["takeoff_material"] = material
        out["takeoff_galvanize"] = galvanize
        out["takeoff_tax"] = tax
        out["takeoff_freight"] = freight
    out["sub_total"] = sub_total

    # ---- spreads ----------------------------------------------------------
    materials_total = 0.0
    sp = item.get("spreads")
    if sp:
        qty_sub = _spreads_qty_subtotal(sp, ctx, pack, tag, carries)
        ctx["spreads.concrete_qty"] = qty_sub
        out["concrete_qty"] = qty_sub
        mats = []
        first_qty = None
        for mat in sp.get("materials") or []:
            raw = mat["qty"]
            if isinstance(raw, (int, float)):
                qty = float(raw)
            elif "qty_subtotal" in str(raw):
                qty = qty_sub
            elif "mat_first" in str(raw):
                qty = first_qty if first_qty is not None else 0.0
            else:
                qty = evaluate(raw, ctx, carries=carries,
                               where=f"{tag} spreads material {mat['name']}")
            if first_qty is None:
                first_qty = qty
            amount = qty * mat["unit_price"]
            mats.append((mat["name"], qty, mat.get("uom", ""),
                         mat["unit_price"], amount))
            materials_total += amount
        out["materials"] = mats
    out["materials_total"] = materials_total

    # ---- cost details -----------------------------------------------------
    details = []
    cost_detail_total = 0.0
    for cd in item.get("cost_details") or []:
        sub = 0.0
        if "header_price" in cd:
            sub += cd["header_price"] * item_qty
        prev_qty = 0.0
        for line in cd.get("lines") or []:
            raw = str(line["qty"])
            # "=D{r-1}" is the template's carry-the-line-above idiom (e.g.
            # TOOLS rides the PICKUP hours). Without it the total understates.
            if re.fullmatch(r"=\s*D\{r-1\}", raw):
                qty = prev_qty
            else:
                qty = evaluate(line["qty"], ctx, carries=carries,
                               where=f"{tag} {cd['name']} {line['name']}"
                               if line.get("name") else f"{tag} {cd['name']}")
            # A formula is legal here: that is how a line carries a share of
            # a shared-cost sheet. Multiplying it raw would raise TypeError
            # on the string.
            unit_price = evaluate(line["unit_price"], ctx, carries=carries,
                                  where=f"{tag} {cd['name']} {line['name']} unit_price"
                                  if line.get("name") else f"{tag} {cd['name']} unit_price")
            sub += qty * unit_price
            prev_qty = qty
        ctx[f"cost_detail[{cd['name']}].subtotal"] = sub
        details.append((cd["name"], sub))
        cost_detail_total += sub
    out["cost_details"] = details
    out["cost_detail_total"] = cost_detail_total

    out["item_total"] = (labor_total + materials_total
                         + cost_detail_total + sub_total)
    return out


def _markup(raw, subtotal: float, carries: list | None = None) -> float:
    """A dollar figure, or a cover formula on the subtotal cell
    ("=E{row:subtotal}*0.10")."""
    if isinstance(raw, dict):
        raise FormulaError(
            "summarize prices a markup number or formula; markup by cost type "
            "is priced in the workbook by a pack that lays out a markup sheet")
    if isinstance(raw, str):
        raw = re.sub(r"\$?E\$?\{row:subtotal\}", f"({subtotal!r})", raw)
    return evaluate(raw, {}, 0.0, carries=carries, where="markup")


def summarize(spec: dict, *, pack=None) -> dict:
    """Price every item in the spec; return per-item and bid totals.

    Returns::

        {"project": str, "bid_date": str,
         "items": [{"sheet", "item_no", "description", "qty", "uom",
                    "labor_total", "manhours", "foreman_days",
                    "materials_total", "cost_detail_total", "sub_total",
                    "item_total", ...}, ...],
         "subtotal": float,      # sum of item totals (direct cost)
         "markup": float,
         "bid_total": float}     # subtotal + markup
    """
    from estimating_tools.estimate_spec.format_pack import bundled_pack, require_support

    require_support(pack or bundled_pack(), "summarize")
    rates = {r["trade"]: float(r["rate"])
             for r in spec.get("rate_table") or []}
    carries: list = []
    items = [price_item(item, rates, carries, pack=pack)
             for item in spec.get("items") or []]
    # A shared-cost sheet (`in_summary: false`) is priced and reported, but
    # its dollars reach the bid through the shares the paying items carry.
    # Summing it here as well is the double-count the flag exists to prevent.
    subtotal = sum(priced["item_total"]
                   for priced, item in zip(items, spec.get("items") or [])
                   if item.get("in_summary") is not False)
    markup = _markup(spec.get("markup", 0), subtotal, carries)
    return {"project": spec.get("project", ""),
            "bid_date": spec.get("bid_date", ""),
            "items": items,
            "subtotal": subtotal,
            "markup": markup,
            "bid_total": subtotal + markup,
            # sheet-relative formulas priced at their default — surfaced so a
            # load-bearing qty carried forward is visible, never silent.
            "carried_forward": carries}


def render_summary(result: dict) -> str:
    """One line per item + the grand-total block, for the CLI."""
    lines = [f"{result['project']}   bid {result['bid_date']}".rstrip(),
             "=" * 78]
    for item in result["items"]:
        lines.append(f"{item['sheet']:<24} {item['description'][:36]:<36} "
                     f"${item['item_total']:14,.0f}")
    lines.append("=" * 78)
    lines.append(f"{'SUBTOTAL (direct cost)':<61} ${result['subtotal']:14,.0f}")
    lines.append(f"{'Markup / bond':<61} ${result['markup']:14,.0f}")
    lines.append(f"{'BID':<61} ${result['bid_total']:14,.0f}")
    carried = result.get("carried_forward") or []
    if carried:
        lines.append("")
        lines.append(f"WARNING: {len(carried)} formula(s) carried forward at "
                     "their default (sheet-relative refs this tool cannot "
                     "resolve) — verify these price correctly in Excel:")
        for c in carried:
            lines.append(f"  {c['where']}: {c['formula']} -> {c['default']:g}")
    return "\n".join(lines)
