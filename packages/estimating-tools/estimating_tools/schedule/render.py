"""Render a LoadedSchedule → markdown (cash-flow + manpower), CSV, and xlsx.
Pure; no ifcopenshell, no MCP. Markdown is meant to be shown verbatim."""
from __future__ import annotations

import csv as _csv
import io


def _rows(loaded, bucket):
    return loaded.by_week if bucket == "week" else loaded.by_month


def render(loaded, *, bucket: str = "month") -> str:
    rows = _rows(loaded, bucket)
    out: list[str] = []
    out.append(f"# 5D Load — {loaded.name}")
    out.append("")
    out.append(f"**Total cost** ${loaded.total_cost:,.0f} · "
               f"**labor** {loaded.total_labor_hours:,.0f} hr · "
               f"**Peak crew** {loaded.peak_workers:,.1f} workers "
               f"({loaded.peak_period}) · {loaded.work_hours_per_day:g} hr/day")
    out.append("")
    out.append("## Cash Flow")
    out.append(f"| Period | Cost | Cumulative | % |")
    out.append("|---|--:|--:|--:|")
    for p in rows:
        pct = (p.cumulative_cost / loaded.total_cost * 100) if loaded.total_cost else 0.0
        out.append(f"| {p.period} | ${p.cost:,.0f} | ${p.cumulative_cost:,.0f} "
                   f"| {pct:.0f}% |")
    out.append("")
    out.append("## Manpower")
    out.append("| Period | Labor hr | Avg workers | Peak workers |")
    out.append("|---|--:|--:|--:|")
    for p in rows:
        out.append(f"| {p.period} | {p.labor_hours:,.0f} | {p.avg_workers:,.1f} "
                   f"| {p.peak_workers:,.1f} |")
    if loaded.unloaded_cost or loaded.no_hours_items or loaded.unpriced_tasks:
        out.append("")
        out.append("## Coverage")
        if loaded.unloaded_cost:
            tot = sum(loaded.unloaded_cost.values())
            out.append(f"- Unloaded cost (no task): {len(loaded.unloaded_cost)} "
                       f"item(s), ${tot:,.0f}")
        if loaded.no_hours_items:
            out.append(f"- Priced without labor: {len(loaded.no_hours_items)} item(s)")
        if loaded.unpriced_tasks:
            out.append(f"- Unpriced tasks: {len(loaded.unpriced_tasks)}")
    return "\n".join(out)


def to_csv(loaded, *, bucket: str = "month") -> str:
    buf = io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(["period", "start", "end", "cost", "cumulative_cost",
                "labor_hours", "avg_workers", "peak_workers"])
    for p in _rows(loaded, bucket):
        w.writerow([p.period, p.start, p.end, p.cost, p.cumulative_cost,
                    p.labor_hours, p.avg_workers, p.peak_workers])
    return buf.getvalue()


def to_xlsx(loaded, path: str, *, bucket: str = "month") -> str:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "5D Load"
    ws.append(["period", "start", "end", "cost", "cumulative_cost",
               "labor_hours", "avg_workers", "peak_workers"])
    for p in _rows(loaded, bucket):
        ws.append([p.period, p.start, p.end, p.cost, p.cumulative_cost,
                   p.labor_hours, p.avg_workers, p.peak_workers])
    wb.save(path)
    return path
