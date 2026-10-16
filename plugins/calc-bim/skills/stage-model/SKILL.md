---
name: stage-model
description: Show a project's construction staging — embed a schedule into the IFC and animate it on the Google Earth time slider. Resolve each task to its bid item codes (estimator-confirmed), run est-bim schedule to author the IfcWorkSchedule and assign elements, then est-bim kml --schedule to stamp per-element TimeSpans. Use when the user wants to see how a project goes together over time, a 4D/staging view, or the schedule played back on the model. Triggers include "show the staging", "4D", "animate the schedule", "how the bridge goes together", "play the schedule in Google Earth".
---

# Stage a Model (schedule → IFC 4D → Google Earth animation)

Turn a project's schedule and its georeferenced IFC into an animated staging
view: the schedule is embedded into the IFC as a native `IfcWorkSchedule`
(readable by Bonsai and Synchro too), and Google Earth's time slider plays
each element appearing on its task's start date. The task→element join is the
same classification-code spine the takeoff uses (see the estimating-tools
`docs/ifc-takeoff-contract.md`).

## Prerequisites
Requires ifcopenshell and pyproj, both in the base install; run
`~/.estimating/bin/est-bim --help` to confirm. If that command is not found,
see the **Setup** block above.

## Inputs
- A **georeferenced** takeoff IFC (`dxf-to-bim` output, est-bim >= 0.1.11 —
  the same model `show-structure-earth` uses) whose elements carry
  classification codes.
- A **schedule file** — any of: GanttWarrior `.gw.json`, Primavera P6 `.xer`,
  or MS Project MSPDI `.xml` (convert a binary `.mpp` to MSPDI first with
  MPXJ). `~/.estimating/bin/est-bim schedule` dispatches on the extension; a GC's P6 baseline
  drives the same staging as your own GanttWarrior export.

## Workflow
1. **Resolve the task → element join, and confirm it.** A task claims its
   IFC elements by any of three matchers, resolved in this order — surface
   the result and let the estimator confirm before embedding:
   - an explicit **task map** you write (JSON, keyed by task id or WBS) —
     highest precedence. A value is either a list of **bid item codes**
     (`["510120", …]`) or, for models with no classification codes
     (parametric builders, Revit/Tekla exports — see the note below), a dict
     of selectors. Keys are the task **id** or **WBS** (matched in that
     order) — NOT the task name; the resolver looks up `task.id` then
     `task.wbs`, so a name key silently matches nothing:
     ```json
     {
       "3.2":    {"name_re": "^RW\\d|retaining wall"},
       "3.3":    {"ifc_class": "IfcPile"},
       "conc-1": {"codes": ["510120"]}
     }
     ```
     (here `3.2`/`3.3` are task WBS codes and `conc-1` is a task id.)
     `name_re` matches each element's Name; `ifc_class` matches its IFC
     class (e.g. `IfcPile`, `IfcFooting`, `IfcWall`); any of the three
     (codes / name_re / ifc_class) assigns.
   - codes the task **name** carries — pass `--name-code-re '<regex>'` and its
     first capture group is extracted per task (e.g. an activity-ID prefix
     like `AB.1020` that maps to a bid item);
   - the org's **job-cost codes** (which embed the bid item number) via the
     BidSheet.ai estimate — propose these to the estimator when neither of the
     above covers a task; there is no silent auto-mapping.
   Every leaf task that claims nothing, every code/selector that matches no
   element, and every element no task claims, is reported by the next step —
   review all three.

   **Which matcher?** If the IFC was authored by `dxf-to-bim` (or otherwise
   carries `IfcClassificationReference` codes), use codes. If it came from a
   parametric builder or a Revit/Tekla export (no codes — check with
   `~/.estimating/bin/est-bim takeoff` reporting "no classification"), use `name_re` /
   `ifc_class`; a project's QTO element-mapping (name-regex + IFC-type rules)
   is often exactly the selector set you want.
2. **Embed the schedule into the IFC:**
   ```bash
   ~/.estimating/bin/est-bim schedule --ifc model.ifc --schedule schedule.gw.json \
       [--task-map task_map.json] [--name-code-re '<regex>'] \
       [--name "<schedule name>"] --out model.4d.ifc
   ```
   It authors one `IfcWorkSchedule` (idempotent by name), the task tree, task
   dates, a work calendar, dependencies, and the element assignments, then
   prints the counts and the both-ways review gaps (tasks with no matching
   element; elements no task schedules) to stderr. Fix the map and re-run if
   the gaps are wrong — re-running replaces the schedule by name.
3. **Animate in Google Earth:**
   ```bash
   ~/.estimating/bin/est-bim kml --schedule model.4d.ifc --out staging.kml
   ```
   Each scheduled element gets a `<TimeSpan>` beginning at its task's start
   date (open-ended — elements appear and persist). For a **detailed model**
   (a full bridge is millions of triangles — the per-element KML can be
   gigabytes and Google Earth won't open it), add `--massing`: each element
   is drawn as its bounding-box block, a few MB, the right level of detail
   for watching volumes appear. Open `staging.kml` in
   Google Earth and use the **time slider** to play the construction staging;
   unscheduled elements stay visible throughout. The command reports how many
   elements carry a TimeSpan.

   **Altitudes.** The site datum comes from the IFC's
   `IfcMapConversion.OrthogonalHeight` automatically, and the command prints
   the shift it applied — check that number against the plan's DATUM
   ELEVATION note before trusting the result. Google Earth reads absolute
   altitude above the **EGM96 geoid** while a US plan-set model is **NAVD88**,
   so the model still floats by the local separation (decimetres) unless you
   pass `--geoid-shift-m`. Derive it once online with
   `bimforge.terrain.datum.geoid_shift_m` and pin it; without the PROJ geoid
   grids that function now refuses to guess rather than handing back a
   null-transform value.
4. **(Optional) hand the 4D IFC to the pros.** `model.4d.ifc` carries a real
   `IfcWorkSchedule` — open it in Bonsai (Blender) for a rendered 4D
   animation, or exchange it with Synchro / Tekla via the usual IFC interop
   path. `show-structure-earth` still gives the static Google Earth web KMZ.

5. **(Optional) read the 4D IFC back.** Any 4D IFC can be read back into
   CanonicalSchedule JSON. That includes one from step 2, one a GC or
   GanttWarrior sends, and one post-processed for Bonsai playback. Add a
   takeoff map to split each takeoff row by task:
   ```bash
   ~/.estimating/bin/est-bim schedule-read --ifc model.4d.ifc [--schedule "<name>"] \
       --out schedule.json [--takeoff-map takeoff_map.yaml --takeoff-out by_task.json]
   ```
   The schedule JSON carries:
   - task ids, WBS, dates and dependencies;
   - the calendars, including recurring blackouts;
   - the task types, owner bid items and notes;
   - each task's IfcTask GlobalId.

   For a 5D model (after `~/.estimating/bin/est-bim cost5d`), add `--costs-out costs.json` to
   get each task's costs and crew hours as well.

   Each takeoff row gains `tasks` ({task id: quantity}) and `unassigned`.
   Only construction-type tasks claim quantity, never removal or demolition
   tasks. Report every row whose `unassigned` is not zero, since that
   quantity belongs to no task.

## Notes
- The **animation surface is KML**, not KMZ: Google Earth animates a
  `<TimeSpan>` per placemark, and the KML writer emits one placemark per
  element. The `show-structure-earth` KMZ is the same per-element polygon KML,
  zipped for Google Earth web, but without TimeSpans, so it cannot stage per-element — use it for the
  static view, `stage-model` for the animation.
- Only elements assigned to a dated task are timed. A task with a bid item
  code that matches no element in the IFC (reported in step 2) usually means
  the code didn't make it onto the geometry — fix the layer/takeoff map, not
  the schedule.
- Construction semantics only: elements appear at task start and stay.
  Demolition, temporary works, and progress/actual-date playback are not
  modelled yet.
