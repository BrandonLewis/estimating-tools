#!/usr/bin/env python3
"""Port the Claude Code plugin's SKILL.md files into OpenWorker's skill format.

OpenWorker (github.com/andrewyng/openworker) loads Anthropic-format `SKILL.md`
folders from two directories (`coworker/agent.py::_skill_dirs`):

    <state-dir>/skills/<name>/SKILL.md          # global
    <workspace>/.coworker/skills/<name>/SKILL.md  # per-workspace

The *format* is the same one Claude Code uses, so the bodies port almost
verbatim. Three things do NOT carry over, and this script rewrites them:

1. `${CLAUDE_PLUGIN_ROOT}` / "<plugin-root>" — OpenWorker has no plugin root and
   no SessionStart hook to pre-install the wheel. `load_skill(name)` hands the
   model a `resources_path` (the skill's own directory) instead, so the setup
   line is rewritten against that.

2. MCP tool names — OpenWorker namespaces every MCP tool as
   `mcp__<server>__<tool>` (`coworker/mcp/tools.py::tool_name`). Bare names like
   `list_bid_items` would never resolve, so known tool names are prefixed.

3. The `open_artifact_editor` display contract — same namespacing rule.

Run from the repo root:  python openworker/port_skills.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_GLOB = "plugins/*/skills/*/SKILL.md"
DEST = REPO_ROOT / "openworker" / "skills"

# The MCP server names this port standardizes on. They must match the keys in
# openworker/mcp/mcpServers.template.json, because OpenWorker derives the tool
# prefix from the config key, not from anything the server reports.
BIDMANAGER = "bidmanager"
ARTIFACT_EDITOR = "artifact-editor"

# BidSheet.ai tool names as the skills use them. The live MCP tool list is
# the authority (estimating-reference points at it); extend this list
# whenever a skill mentions a new BM tool so the port can prefix it.
BIDMANAGER_TOOLS = [
    # projects
    "list_projects", "get_project", "create_project", "update_project", "search_projects",
    # bid items
    "list_bid_items", "get_bid_item", "get_bid_item_pricing", "search_bid_items_by_code",
    "create_bid_item", "update_bid_item", "bulk_create_bid_items", "bulk_update_bid_items",
    # bid schedules / item templates
    "list_bid_schedules", "create_bid_schedule",
    "search_bid_item_templates", "create_bid_item_template", "update_bid_item_template",
    # bid-item scaffolds (workbook prefill catalog — build-estimate-workbook skill)
    "list_bid_item_scaffolds", "lookup_bid_item_scaffold",
    "create_bid_item_scaffold", "update_bid_item_scaffold", "delete_bid_item_scaffold",
    # estimates
    "list_estimates", "get_estimate", "create_estimate", "update_estimate", "delete_estimate",
    "list_estimate_items", "create_estimate_item", "update_estimate_item",
    "delete_estimate_item", "get_estimate_summary",
    # estimate templates (whole-bid-structure reuse)
    "list_estimate_templates", "get_estimate_template", "save_estimate_as_template",
    "instantiate_estimate_from_template", "delete_estimate_template",
    # estimate packages
    "list_estimate_packages", "create_estimate_package", "update_estimate_package",
    "add_estimate_package_member", "recalculate_estimate_package_totals",
    # structures (the takeoff's home on the estimate — push-takeoff skill)
    "create_structure", "get_structure", "list_structures",
    "add_structure_section", "remove_structure_section", "delete_structure",
    # assemblies
    "list_assemblies", "get_assembly", "create_assembly", "update_assembly", "delete_assembly",
    "bulk_create_assemblies",
    "clone_assembly", "list_components", "create_component", "update_component",
    "delete_component",
    # rate library
    "list_labor_rates", "list_equipment_rates", "list_material_costs", "get_current_rate",
    "create_labor_rate", "create_equipment_rate", "create_material_cost",
    # work packages
    "list_work_packages", "get_work_package", "create_work_package", "update_work_package",
    "assign_items_to_package", "remove_items_from_package",
    # quotes
    "list_quotes", "get_quote", "create_quote", "update_quote", "update_quote_status",
    "get_best_quote",
    # work-package quotes (grouped quoting: header + per-item lines + revisions)
    "list_work_package_quotes", "create_work_package_quote",
    "update_work_package_quote", "set_quote_scope_tags",
    "list_work_package_quote_line_items", "create_work_package_quote_line_item",
    "update_work_package_quote_line_item",
    "list_quote_revisions", "create_quote_revision",
    # solicitations / ITB records (solicit-quotes / quote-coverage skills)
    "list_solicitations", "record_solicitation",
    # subcontractor allocations (awarding a quote to the estimate)
    "list_subcontractor_allocations", "allocate_subcontractor",
    "update_subcontractor_allocation", "remove_subcontractor_allocation",
    # workflows
    "price_bid_item", "build_assembly_breakdown", "prepare_estimate_summary",
    "analyze_bid_competitiveness",
    # directory / cost codes (used by the import-* skills)
    "list_organizations", "create_organization", "get_organization", "update_organization",
    "list_contacts", "create_contact",
    "list_people", "create_person", "update_person", "add_person_to_organization",
    "list_cost_codes", "create_cost_code", "list_cost_types", "create_cost_type",
    "create_cost_code_system", "list_cost_code_systems",
    "create_activity_code", "find_activity_code_by_code",
    # historical pricing bank (import-historicals / price-estimate lookups)
    "create_historical_record", "bulk_create_historical_records",
    "list_historical_records", "record_competitor_bid", "get_bid_result",
    # feedback reports (report-issue / triage-feedback skills)
    "create_feedback_report", "list_feedback_reports", "update_feedback_report",
]

ARTIFACT_EDITOR_TOOLS = ["open_artifact_editor", "collect_artifact_edits"]

# The OpenWorker replacement for the plugin's `> **Setup:** ...` line. The plugin
# version points at `<plugin-root>/dist/*.whl`; under OpenWorker the wheel rides
# along in `skills/_dist/`, which `load_skill` reaches via `resources_path`.
#
# `| tail -1` is load-bearing, not decoration: the glob sits inside a QUOTED
# command substitution, so if `_dist` ever holds two versions of a wheel the
# expansion collapses into ONE argument containing newline-separated paths and
# pip rejects it — silently breaking this fallback in every ported skill at
# once. Stale 0.1.53/0.1.59 copies did exactly that until they were removed;
# `tail -1` keeps the command correct even if a later release forgets to delete
# its predecessor.
SETUP_LINE = (
    "> **Setup:** If `import estimating_tools` fails, install the bundled wheels: "
    "`pip install \"$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)\" "
    "\"$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]\"` "
    "— `<resources_path>` is the path `load_skill` returned for this skill. "
    "Then retry. (`openworker/install.py` normally does this at install time, so "
    "you should only need the fallback on a fresh or relocated Python env.)"
)

_SETUP_RE = re.compile(
    r"^> \*\*Setup:\*\*.*?(?=\n\n|\n> \*\*|\Z)", re.MULTILINE | re.DOTALL
)

# The artifact-editor server is deliberately not shipped in the OpenWorker
# build (see README "The artifact-editor server is deliberately not shipped"),
# so its tools are never present here. The old rationale — non-Apps hosts get
# an empty list_tools — no longer holds: since estimating_tools 0.1.8 the
# server exposes a browser mode (loopback HTTP editor) to tools-only clients,
# so shipping it under OpenWorker is a viable follow-up. Until that decision,
# say the tool is absent up front rather than letting the model probe for it
# every render.
DISPLAY_NOTE = (
    "> **On OpenWorker:** the `artifact-editor` server is not shipped in this "
    "build, so its tools are absent. Skip the "
    "`open_artifact_editor` branch below and go straight to the "
    "`to_editable_html` page path. If the session has `send_file` (a messaging "
    "persona), hand the written `.artifact.html` to the user with it.\n\n"
)

_DISPLAY_RE = re.compile(r"^> \*\*Display contract:\*\*", re.MULTILINE)


def namespace_tools(text: str) -> tuple[str, int]:
    """Prefix bare MCP tool names with OpenWorker's `mcp__<server>__` namespace.

    The negative lookbehind on `_` keeps the pass idempotent (a name that is
    already namespaced ends in `..._` before the match and is skipped).
    """
    count = 0
    for server, tools in ((BIDMANAGER, BIDMANAGER_TOOLS), (ARTIFACT_EDITOR, ARTIFACT_EDITOR_TOOLS)):
        for tool in tools:
            pattern = re.compile(rf"(?<![\w_]){re.escape(tool)}(?![\w])")
            text, n = pattern.subn(f"mcp__{server}__{tool}", text)
            count += n
    return text, count


def rewrite_setup(text: str) -> tuple[str, bool]:
    """Swap the plugin's wheel-install line for the OpenWorker one."""
    if "**Setup:**" not in text:
        return text, False
    return _SETUP_RE.sub(lambda _: SETUP_LINE, text, count=1), True


def strip_plugin_root(text: str) -> str:
    """Remove the remaining `${CLAUDE_PLUGIN_ROOT}` references (no plugin root here)."""
    return text.replace("${CLAUDE_PLUGIN_ROOT}", "<resources_path>/..")


def annotate_display_contract(text: str) -> tuple[str, bool]:
    """Prepend the OpenWorker reality note ahead of the display contract."""
    if "**Display contract:**" not in text or DISPLAY_NOTE.strip() in text:
        return text, False
    return _DISPLAY_RE.sub(
        lambda m: DISPLAY_NOTE + m.group(0), text, count=1
    ), True


#: The plugins' shim directory. OpenWorker has no plugin runtime and no hook
#: that could build one -- its setup line tells the user to pip install into the
#: interpreter they are running, which puts the console scripts on PATH the
#: ordinary way. A path under `~/.estimating/bin/` would simply not exist there,
#: so it is stripped back to the bare name on the way out.
SHIM_BIN = "~/.estimating/bin/"


def strip_shim_paths(text: str) -> tuple[str, int]:
    n = text.count(SHIM_BIN)
    # `est-python` has no ambient equivalent; the plain interpreter is right.
    return text.replace(SHIM_BIN + "est-python", "python").replace(SHIM_BIN, ""), n


def port_body(text: str) -> tuple[str, dict]:
    text, shims = strip_shim_paths(text)
    text, setup = rewrite_setup(text)
    text, display = annotate_display_contract(text)
    text = strip_plugin_root(text)
    text, ns = namespace_tools(text)
    return text, {
        "setup_rewritten": setup,
        "display_annotated": display,
        "tools_namespaced": ns,
        "shims_stripped": shims,
    }


def frontmatter_name(text: str) -> str | None:
    """Read `name:` the way OpenWorker's loader does — line-based, not YAML.

    `coworker/skills/base.py::_parse_skill` splits each frontmatter line on the
    first `:` rather than parsing YAML, so the name must be a single plain line.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == "name":
            return value.strip() or None
    return None


def sync_wheels(*, check: bool) -> list:
    """Copy -- or with `check`, verify -- the wheels that ride along in `_dist`.

    The skills' install fallback points at these: OpenWorker has no hook that
    could fetch them later, so a stale copy ships the previous release's
    behaviour to every OpenWorker user. Since the bimforge split,
    estimating_tools needs the sibling bimforge wheel too.

    `--check` used to return before this ran, so the drift guard passed while
    `_dist/estimating_tools-*.whl` still held older code -- caught in review on
    PR #296, where the source carried a new gate and this wheel did not.
    Comparing BYTES is the point: the filename does not change within a release,
    so a name or version check would have seen nothing wrong.
    """
    def dist_dir():
        return DEST / "_dist"

    stale = []
    for prefix in ("estimating_tools", "bimforge"):
        wheels = sorted((REPO_ROOT / "plugins" / "estimating-core" / "dist")
                        .glob(f"{prefix}-*.whl"))
        if not wheels:
            continue
        src = wheels[-1]
        dest = dist_dir() / src.name
        # Superseded copies are a real bug, not clutter: openworker/install.py
        # takes sorted(...)[-1] and every ported skill's Setup line globs this
        # directory. Copies for 0.1.53 and 0.1.59 accumulated and went unnoticed
        # for several releases, which is why RELEASING.md has to ask for a
        # `git rm` by hand -- "no guard catches a leftover". This is the guard.
        superseded = [q for q in dist_dir().glob(f"{prefix}-*.whl")
                      if q.name != src.name]
        if check:
            if not dest.is_file() or dest.read_bytes() != src.read_bytes():
                stale.append(f"_dist/{src.name}")
            stale += [f"_dist/{q.name} (superseded by {src.name})"
                      for q in superseded]
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"\nwheel -> {dest}")
        for q in superseded:
            q.unlink()
            print(f"removed superseded {q.name}")
    return stale


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed port matches the sources; write nothing")
    args = ap.parse_args(argv)

    sources = sorted(REPO_ROOT.glob(SRC_GLOB))
    if not sources:
        print(f"no SKILL.md found under {REPO_ROOT}/{SRC_GLOB}", file=sys.stderr)
        return 1

    stale: list[str] = []
    seen: dict[str, Path] = {}
    for src in sources:
        raw = src.read_text(encoding="utf-8")
        name = frontmatter_name(raw)
        if not name:
            print(f"skip (no `name:` in frontmatter): {src}", file=sys.stderr)
            continue
        if name in seen:
            # OpenWorker keys skills by name in one flat dict — a collision would
            # silently drop one of them.
            print(f"ERROR: duplicate skill name {name!r}: {seen[name]} and {src}", file=sys.stderr)
            return 1
        seen[name] = src

        ported, stats = port_body(raw)
        out = DEST / name / "SKILL.md"
        # Auxiliary docs under the skill's references/ ride along verbatim —
        # nothing in them needs porting, but SKILL.md pointers to them must resolve.
        refs = src.parent / "references"
        ref_files = sorted(p for p in refs.rglob("*") if p.is_file()) if refs.is_dir() else []
        if args.check:
            if not out.is_file() or out.read_text(encoding="utf-8") != ported:
                stale.append(name)
            for ref in ref_files:
                dest_ref = out.parent / "references" / ref.relative_to(refs)
                if not dest_ref.is_file() or dest_ref.read_bytes() != ref.read_bytes():
                    stale.append(f"{name}/references/{ref.relative_to(refs).as_posix()}")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(ported, encoding="utf-8")
        for ref in ref_files:
            dest_ref = out.parent / "references" / ref.relative_to(refs)
            dest_ref.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ref, dest_ref)
        print(f"{name:28s} setup={'y' if stats['setup_rewritten'] else '-'} "
              f"display={'y' if stats['display_annotated'] else '-'} "
              f"tools_namespaced={stats['tools_namespaced']} "
              f"shims_stripped={stats['shims_stripped']}"
              + (f" refs={len(ref_files)}" if ref_files else ""))

    stale += sync_wheels(check=args.check)

    if args.check:
        if stale:
            print(f"stale ported skills: {', '.join(sorted(set(stale)))}", file=sys.stderr)
            print("Run: python openworker/port_skills.py", file=sys.stderr)
            return 1
        print(f"{len(seen)} ported skills are up to date")
        return 0

    print(f"\n{len(seen)} skills ported to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
