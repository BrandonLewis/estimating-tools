---
name: read-station-plans
description: Read station-detailed civil/structural plan sheets into citable parameters — station/offset callouts, section tables keyed by design H, standard-plan references, transcribe-then-verify YAML discipline. Use BEFORE build-structure or measure-plans when the input is a plan set with stationing, wall tables, or standard-plan details. Triggers include "read the wall table", "transcribe the plans", "station and offset", "design H table", "standard plan section".
---

# Read Station Plans

Interpretive knowledge for turning plan sheets into parameters a parametric
build can trust. The output is a CITABLE TRANSCRIPTION: every dimension
carries the sheet and detail it was read from, so a reviewer can audit it
and an RFI can cite it. Nothing is scaled off a drawing without saying so.

## The two routes — choose deliberately
Classify the document type FIRST: CAD-plotted agency plan sheets are vector
geometry with flattened text — a fourth type alongside text-based, scanned,
and mixed — and route to vector detection, never OCR (the linework is exact;
reading it as an image throws that exactness away).
- **Compute from tables** (this skill + `build-structure`): the sheets give
  stations, elevations and a section table keyed by a design dimension.
  Standard-plan tables use XLOOKUP-up semantics: design H rounds UP to the
  next tabulated size ("may be exceeded by 6 in before going to the next
  size"). Prefer this route whenever the geometry is table-driven.
- **Trace vector geometry** (`measure-plans`): the quantity lives in drawn
  linework (irregular footprints, limits of pay). Use when no closed form
  exists. Both routes end at the same IFC -> takeoff junction.

## Reading discipline (hard-won; keep all of it)
- **Station/offset callouts:** offsets are RADIAL (perpendicular to the
  tangent at that station), signed by side (Lt/Rt of increasing station).
  An anchored alignment (a published coordinate partway along the first
  tangent) is a supported form — back-compute the POB, never eyeball it.
- **The offset between two parallel chains is itself a dimension.** An
  un-lettered offset can be the stagger (lap) between two dimension chains —
  read it as a quantity in its own right, never a value to invent.
- **Whose table is it?** A project's own table (a sheet-numbered
  TABLE OF ... DIMENSIONS AND DATA) beats the standard plan it resembles —
  do not substitute the standard's values. Record which one you transcribed.
- **Classify a break before counting it.** On a wall elevation, one edge
  jogging is a THICKNESS change; both edges jogging is a STEP. Count them
  separately or the step count lands ~75% over.
- **Confirm scale on a known quantity, then find a second independent hit.**
  One confirmation is a coincidence.
- **When the graphic and the label disagree, the label that closes the
  dimension chain wins.**
- **Parallel lines a plausible thickness apart are not necessarily a
  member.** Fences, trail edges, revetment bands and easement strips all
  draw as 1–3 ft pairs. Check what the sheet LETTERS next to it, what the
  companion section shows there, and the segment count against the span
  (a filled strip has ~100 segments; a wall face is one long line).
- **A measured length that misses the paid quantity is a FINDING** — report
  the gap and the implied unit rate; never invent geometry to close it.
- **A level surface under a sloping one produces a varying gap** — never a
  constant.
- **Survey-grade vs approximate:** coordinates georeferenced from imagery
  or scaled plans are navigation-grade (± tens of feet) — flag every output
  built on them `grade: approximate`; downstream sheets stamp NOT FOR
  CONSTRUCTION LAYOUT and KML emitters label the source approximate.
  (Canonical grade rule: the `drafting-agent` agent.)
- **Run-shaped elements on a skew or curve carry their dims as INPUTS,
  never a bounding box.** A barrier or band strip running diagonal to the
  axes has a bbox that reads ≈ its own length in BOTH dimensions (a 14 ft ×
  14 ft box on a 19 SF footprint); on a real bid the barrier LF read 956
  against a true 1,180 — a silent −19%. Transcribe the station span and the
  section width as explicit parameters and carry them on the element (the
  kernel's `Prism.dims_ft` exists for exactly this) — never reverse-engineer
  a run's L or W from its polygon.
- **An ambiguous hatched member is confirmed by TWO independent geometric
  tells, jointly.** Check its proportion against a dimensioned neighbor AND
  whether its dimension fills an adjacent dimensioned gap — neither
  alone is conclusive. (The classic misread shipped through three
  "corrected" revisions before both tells were checked: the member drew ~2×
  the width of the dimensioned 3/8" end plate beside it, and its 5¾"
  filled the 5⅞" gap it sat in — a web, not the pad it had been read as;
  the ⅛" residual is itself information, resolved by deriving the
  centreline.) A leader pointing into
  open space beside a member is the tell for a plate BEYOND the cut plane,
  not a callout on the hatched member itself.
- **A dimensioned member governs an approximate callout.** When a chain of
  dimensioned members lets you DERIVE a value the sheet only gives as
  "APPROX", derive it, use the derived value, and cross-check it against
  the APPROX with a stated tolerance — transcribing the approximation
  throws away the sheet's own better answer.
- **An addendum that revises controlling geometry revises its dependents.**
  When an addendum touches primary geometry (a deck profile, a controlling
  elevation), enumerate every dependent element — soffit shape, abutment
  seats, bearing-pad spacing, column spacing, pile tips — and re-verify
  each one individually against the revised sheets. Partial revisions
  leave stale, mutually inconsistent geometry that no single sheet
  reveals; any dependent that no longer closes goes to `open_questions:`.

## Output form
YAML params for `build-structure` (or a briefing annex): dimension groups
with `source:` sheet/detail citations; sheet-underdetermined values as
`assumptions: [{key, value, reason}]` (the gate refuses a bare reason);
genuine ambiguities in `open_questions:` for the human — with your best
reading and why. Cross-check every table row you transcribe (e.g. W = C + B
must hold at every design H) BEFORE building anything on it.
