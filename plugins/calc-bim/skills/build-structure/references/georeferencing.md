# Georeferencing & vertical datums for BIM authoring

Setting a model's frame — projected CRS + `IfcMapConversion` + vertical-datum
shift + base point — is judgment-heavy and repeatedly gotten wrong in ways the
volume gates never see (a wrong datum moves geometry without changing its
size). This is the reference the BIM-authoring paths point to. The datum
*authority* is `bimforge.terrain.datum`; this doc is how to use it and which
traps to avoid.

## The frame, in one picture

The house convention keeps geometry **near the model origin** and carries the
real-world position in `IfcMapConversion`, NOT in the vertices:

```
ProjectContext(epsg=<projected CRS>, base_e=<E>, base_n=<N>, base_h=<H>, guid_ns=…)
   → every vertex is LOCAL:  local = survey − base   (feet, x=East, y=North)
   → emit_ifc writes base_e/base_n/base_h into IfcMapConversion
```

Authoring true survey coordinates into vertex Z puts geometry hundreds of
metres from the origin, where a viewer's default view never frames it (the
model reads as empty) and single precision loses resolution. Keep it local;
the datum belongs in `IfcMapConversion` (issues #133/#134).

## 1. Choose the projected CRS (horizontal)

Use the **State Plane zone for the county**, in the **unit the survey is in**.
California SPCS (NAD83), US survey foot — what bimforge models use:

| Zone | ftUS EPSG | Counties (examples) |
|------|-----------|---------------------|
| 1 | 2225 | Del Norte, Siskiyou, Modoc, Humboldt, … |
| 2 | 2226 | Sacramento, El Dorado, Yolo, Sutter, … |
| 3 | 2227 | San Francisco, Santa Clara, Alameda, San Joaquin, … |
| 4 | 2228 | Monterey, Fresno, Kings, … |
| 5 | 2229 | Los Angeles, San Bernardino, Santa Barbara, … |
| 6 | 2230 | San Diego, Imperial, Orange, Riverside |

Set `project.epsg` to that code. The base point (`base: [E, N, H]`) should be a
**published control monument** near the site — geometry then sits a few hundred
feet from the origin at most.

### The unit trap (6414 vs 6417, and 2226 vs 26942)

Every State Plane zone has **two EPSG codes that differ only in unit** — metre
vs US survey foot — and a NAD83 vs NAD83(2011) realization split on top:

- NAD83, zone 3: **2227** (ftUS) — metre twin **26943**.
- NAD83(2011), zone 3: **6417** (ftUS) — metre twin **6414**.

Picking the metre code for a survey delivered in ftUS (or the reverse)
**silently rescales the whole model by 0.3048** and nothing in the volume gate
catches it (an earlier site build shipped a long comment on exactly the 6417-vs-6414
mix-up). Rule: **match the EPSG's unit AND realization to the survey's**, and
if the plan set gives coordinates in feet, use the ftUS code (22xx / 64xx-ftUS),
never the metre twin.

## 2. Choose the vertical datum, and convert if needed

Two different questions, two different shifts — do not conflate them:

### a) NGVD29 → NAVD88 (older plans)

Plan sets before ~1990 are often on **NGVD29**; modern work is **NAVD88**. The
difference is ~0.7–1.0 m in California and varies by location. Convert with
VERTCON via NOAA NCAT 3.0:

```python
from bimforge.terrain.datum import ncat_vertshift
dv = ncat_vertshift(lat, lon, cache_path,           # degrees, WGS84
                    in_vert="NGVD29", out_vert="NAVD88")
```

An earlier site build carried `VSHIFT_M = 0.781` from exactly this lookup. Apply it to
the survey elevations BEFORE they become `base_h` / model Z, so the model is
NAVD88 throughout.

### b) NAVD88 → EGM96 (only for KML absolute altitude)

Google Earth's `altitudeMode=absolute` is height above the **EGM96** geoid,
while the model is **NAVD88** — a different geoid, off by decimetres. This is
NOT a datum error in the model; it is a KML-export correction:

```python
from bimforge.terrain.datum import geoid_shift_m
shift = geoid_shift_m(lat, lon)     # add to a NAVD88 metric height → EGM96
```

`est-bim kml` already applies the model's own `IfcMapConversion.OrthogonalHeight`
as the datum height automatically (#194); pass `--geoid-shift-m <shift>` for
**only** the NAVD88→EGM96 correction on top. `geoid_shift_m` self-checks with a
liveness assertion and refuses a suspiciously-null transform rather than
emitting a model 2440 ft underground (the high-elevation-bridge regression) — if it raises, PROJ lacks the
grid; do not paper over it with 0.

## 3. Set the base point

- `base_e`, `base_n`: the E/N of a **published control monument** on the sheet,
  in the same ftUS zone as `epsg`.
- `base_h`: the monument's **NAVD88** elevation (after any NGVD29→NAVD88 shift),
  in the model's length unit — this becomes `IfcMapConversion.OrthogonalHeight`.

## Common pitfalls (checklist)

- [ ] EPSG unit matches the survey (ftUS ≠ metre — the 0.3048 rescale).
- [ ] EPSG realization matches (NAD83 vs NAD83(2011); 2227 ≠ 6417).
- [ ] Projected CRS, not a geographic one (never 4326 for `project.epsg`).
- [ ] Zone matches the county.
- [ ] Elevations converted to NAVD88 (VERTCON) before they become `base_h`/Z.
- [ ] KML: `--geoid-shift-m` is the NAVD88→EGM96 shift ONLY, never the datum
      height (that's automatic) — and never a hand-pinned 0 to silence a raise.
- [ ] Base point at a control monument, geometry local to it.

## Sources in the kernel

- `bimforge.terrain.datum.ncat_vertshift` — NGVD29↔NAVD88 (NOAA NCAT / VERTCON 3.0).
- `bimforge.terrain.datum.geoid_shift_m` — NAVD88→EGM96 for KML absolute altitude.
- `bimforge.author.project.ProjectContext` — `epsg` + `base_[e,n,h]` → `IfcMapConversion`.
- `est-bim kml` — applies `OrthogonalHeight` by default (#194).
